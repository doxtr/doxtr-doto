"""Tests for the optional Textual TUI (``doto tui``).

These exercise the TUI data helpers, the mutating actions (which route
through the CLI verb functions), and the Textual app itself via
``App.run_test()``/``Pilot``. The ``textual`` dependency is required for the
app/pilot tests; they are guard-skipped if it is missing, but it is installed
in this project's dev/tui extras so they run here.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.config import load_config
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext, cli
from doxtr_doto.cli.output import get_formatter
from doxtr_doto.cli.tui import TEXTUAL_AVAILABLE, actions, data

pytestmark = pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")


# Child-theme widget/screen subclasses used by
# ``test_edit_dialog_widget_classes_are_overridable``. Defined at module level
# (only when textual is importable) so Textual's per-class CSS registration is
# stable, rather than defining App/Screen subclasses inside a test function.
if TEXTUAL_AVAILABLE:
    from doxtr_doto.cli.tui.app import (
        EditTaskScreen as _EditTaskScreen,
    )
    from doxtr_doto.cli.tui.app import (
        KillRingInput as _KillRingInput,
    )
    from doxtr_doto.cli.tui.app import (
        KillRingTextArea as _KillRingTextArea,
    )

    class _ThemedInput(_KillRingInput):
        """Stand-in for a child theme's custom single-line input."""

    class _ThemedTextArea(_KillRingTextArea):
        """Stand-in for a child theme's custom multi-line text area."""

    class _ThemedEditScreen(_EditTaskScreen):
        """Edit screen that swaps in the themed widgets via the *_class seams."""

        input_class = _ThemedInput
        text_area_class = _ThemedTextArea

    from doxtr_doto.cli.tui.app import DotoApp as _DotoApp

    class _ThemedApp(_DotoApp):
        """App whose edit dialog uses the themed screen/widget subclasses."""

        edit_task_screen_class = _ThemedEditScreen

    from doxtr_doto.cli.tui.app import (
        CardViewerScreen as _CardViewerScreen,
    )

    class _ThemedCardViewerScreen(_CardViewerScreen):
        """Stand-in for a child theme's custom card viewer popup."""

    class _ThemedViewerApp(_DotoApp):
        """App whose kanban card viewer uses the themed viewer subclass."""

        card_viewer_screen_class = _ThemedCardViewerScreen

    from doxtr_doto.cli.tui.app import (
        AddTaskScreen as _AddTaskScreen,
    )

    class _ThemedAddTaskScreen(_AddTaskScreen):
        """Stand-in for a child theme's custom add-task modal."""

    class _ThemedAddApp(_DotoApp):
        """App whose add-task modal uses the themed add-task subclass."""

        add_task_screen_class = _ThemedAddTaskScreen

    # Child-theme view subclasses used by
    # ``TestLayoutViews.test_view_classes_are_overridable``. Defined at module
    # level (only when textual is importable) so Textual's per-class CSS
    # registration is stable, mirroring ``_ThemedApp`` above.
    from doxtr_doto.cli.tui.widgets import (
        CalendarView as _CalendarView,
    )
    from doxtr_doto.cli.tui.widgets import (
        KanbanView as _KanbanView,
    )
    from doxtr_doto.cli.tui.widgets import (
        ListView as _ListView,
    )

    class _ThemedListView(_ListView):
        """Stand-in for a child theme's custom list view."""

    class _ThemedKanbanView(_KanbanView):
        """Stand-in for a child theme's custom kanban view."""

    class _ThemedCalendarView(_CalendarView):
        """Stand-in for a child theme's custom calendar view."""

    #: Sentinel a themed view injects into its rendered output so
    #: ``test_overridden_format_reaches_render`` can prove the override's
    #: markup actually reaches the screen, not just that the subclass mounted.
    _RENDER_SENTINEL = "ZZ-THEME-SENTINEL"

    class _SentinelListView(_ListView):
        """A themed list view whose per-line markup emits a sentinel string."""

        @classmethod
        def format_line(cls, task, highlighted):
            """Return the base line prefixed with the render sentinel."""
            base = super().format_line(task, highlighted)
            return f"{_RENDER_SENTINEL} {base}"

    #: Sentinel a themed calendar injects into *highlighted* task entries so
    #: ``test_calendar_highlight_flows_through_seam`` can prove the active-
    #: region highlight routes through the overridable ``format_entry`` seam.
    _CAL_HIGHLIGHT_SENTINEL = "ZZ-CAL-HILITE"

    class _SentinelCalendarView(_CalendarView):
        """A themed calendar whose highlighted entry markup emits a sentinel."""

        @classmethod
        def format_entry(cls, task, highlighted=False):
            """Prefix the highlighted entry with the calendar highlight sentinel."""
            base = super().format_entry(task, highlighted)
            if highlighted:
                return f"{_CAL_HIGHLIGHT_SENTINEL} {base}"
            return base

    class _ThemedLayoutApp(_DotoApp):
        """App whose layout views use the themed view subclasses."""

        list_view_class = _ThemedListView
        kanban_view_class = _ThemedKanbanView
        calendar_view_class = _ThemedCalendarView

    class _SentinelLayoutApp(_DotoApp):
        """App whose list view overrides ``format_line`` to emit a sentinel."""

        list_view_class = _SentinelListView

    class _SentinelCalendarApp(_DotoApp):
        """App whose calendar view marks highlighted entries with a sentinel."""

        calendar_view_class = _SentinelCalendarView


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
    """Isolate the global config in a temp dir.

    ``GlobalStateStore()`` resolves its config path with ``$DOTO_CONFIG``
    taking priority over everything else, then a ``.doto/config.json`` found
    by walking *up* from the cwd, and only then ``$XDG_CONFIG_HOME``. Setting
    only ``XDG_CONFIG_HOME`` is therefore insufficient under this test run:
    the portable walk-up finds the real repo's ``.doto/config.json`` and the
    live-app Pilot tests would read/write TUI preferences (layout, filters,
    ``last_prompt_date``) into it, leaking state across tests and into the
    developer's checkout. Pinning ``DOTO_CONFIG`` to a per-test temp path
    makes isolation complete (and each ``tmp_path`` is fresh, so no state
    leaks between tests).
    """
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


@pytest.fixture
def empty_ctx(tmp_path, env):
    """A DotoContext wired to an empty store (no tasks) and isolated state."""
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
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


@pytest.fixture
def multi_lane_store_file(tmp_path):
    """A JSON store with tasks spread across two kanban status lanes.

    Two tasks are ``open`` and two are ``in-progress`` so the kanban board
    renders at least two non-empty swim lanes side by side, letting a Pilot
    test switch lanes with ``l``/``h`` and verify the Shift+Up / Shift+Down
    jump is relative to the now-current lane.
    """
    store_path = tmp_path / "repoLanes" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {
                "title": "First open task",
                "status": "open",
                "priority": "high",
                "tags": [],
                "worklogs": [],
            },
            "T-002": {
                "title": "Second open task",
                "status": "open",
                "priority": "low",
                "tags": [],
                "worklogs": [],
            },
            "T-003": {
                "title": "First in-progress task",
                "status": "in-progress",
                "priority": "high",
                "tags": [],
                "worklogs": [],
            },
            "T-004": {
                "title": "Second in-progress task",
                "status": "in-progress",
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
def multi_lane_ctx(multi_lane_store_file, env):
    """A DotoContext wired to the two-lane kanban store and isolated state."""
    config = load_config(json_path=multi_lane_store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


@pytest.fixture
def parent_store_file(tmp_path):
    """A JSON store with three open tasks for the set-parent (``e P``) tests.

    Three tasks (T-001/T-002/T-003) so a multi-selection of two children still
    leaves at least one candidate parent after the children are excluded.
    """
    store_path = tmp_path / "repoParent" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {"title": "First task", "status": "open", "worklogs": []},
            "T-002": {"title": "Second task", "status": "open", "worklogs": []},
            "T-003": {"title": "Third task", "status": "open", "worklogs": []},
        },
        "series": {},
    }
    store_path.write_text(json.dumps(data_dict))
    return store_path


@pytest.fixture
def parent_ctx(parent_store_file, env):
    """A DotoContext wired to the three-task set-parent store + isolated state."""
    config = load_config(json_path=parent_store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


@pytest.fixture
def series_store_file(tmp_path):
    """A JSON store with a 3-occurrence series plus a standalone task.

    The three occurrences share a ``series_id`` (``SER-1``) and carry ascending
    ``due`` dates, but their store ids are deliberately ordered so that id
    order does NOT match due-date (occurrence) order: ``S-003`` is the
    *earliest* meeting and ``S-001`` the *latest*. This lets the series-
    navigation tests prove the jump follows occurrence (due-date) order rather
    than id / insertion order. A standalone ``T-100`` (no ``series_id``) covers
    the non-series no-op path.
    """
    store_path = tmp_path / "repoSeries" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "S-003": {
                "title": "Weekly sync (first)",
                "status": "open",
                "priority": "medium",
                "tags": [],
                "worklogs": [],
                "series_id": "SER-1",
                "due": "2026-01-05",
            },
            "S-002": {
                "title": "Weekly sync (second)",
                "status": "open",
                "priority": "medium",
                "tags": [],
                "worklogs": [],
                "series_id": "SER-1",
                "due": "2026-01-12",
            },
            "S-001": {
                "title": "Weekly sync (third)",
                "status": "open",
                "priority": "medium",
                "tags": [],
                "worklogs": [],
                "series_id": "SER-1",
                "due": "2026-01-19",
            },
            "T-100": {
                "title": "Standalone task",
                "status": "open",
                "priority": "low",
                "tags": [],
                "worklogs": [],
            },
        },
        "series": {
            "SER-1": {
                "title_template": "Weekly sync",
                "pattern": {"frequency": "weekly", "interval": 1},
                "start_date": "2026-01-05",
                "end_date": "2026-01-19",
                "task_ids": ["S-003", "S-002", "S-001"],
            }
        },
    }
    store_path.write_text(json.dumps(data_dict))
    return store_path


@pytest.fixture
def series_ctx(series_store_file, env):
    """A DotoContext wired to the 3-occurrence series store and isolated state."""
    config = load_config(json_path=series_store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


# ---------------------------------------------------------------------------
# Long-value fixtures (layout / overflow stress inputs)
#
# These exercise the TUI's handling of degenerate-but-realistic field values
# that are far wider than any pane: a long namespaced id, a long title, a long
# description body, long tags, and a long assignee name. The exact strings are
# shared between the pure-logic tests (format_* classmethods) and the live
# pilot tests so the two stay in lockstep.
# ---------------------------------------------------------------------------
LONG_ID = "noter-2026-03-01-cc33-2024-04-22-L1799"
LONG_TITLE = (
    "Make sure to involve Donald Duck, when taking hard decisions on the "
    "project with phantomas, he knows him well"
)
LONG_BODY = (
    "This is a deliberately long description body that keeps going well past "
    "any reasonable pane width so we can be sure it wraps or scrolls rather "
    "than clipping, overflowing, or breaking the surrounding layout. "
) * 3
LONG_ASSIGNEE = "Donald Fauntleroy Duck de la Mallard III of Duckburg, Calisota"
LONG_TAGS = [
    "a-really-long-tag-name-that-just-keeps-going-and-going",
    "another-extremely-verbose-tag-label-for-good-measure",
]


def _long_task(status: str = "open", **overrides):
    """Return a task dict whose every text field is pathologically long."""
    task = {
        "id": LONG_ID,
        "title": LONG_TITLE,
        "status": status,
        "priority": "high",
        "assignee": LONG_ASSIGNEE,
        "body": LONG_BODY,
        "tags": list(LONG_TAGS),
        "due": "2026-03-01",
        "worklogs": [],
    }
    task.update(overrides)
    return task


@pytest.fixture
def long_ctx(tmp_path, env):
    """A DotoContext whose single task has long id/title/body/tags/assignee."""
    store_path = tmp_path / "long" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    task = _long_task()
    task_id = task.pop("id")
    store_path.write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2024-01-01T00:00:00",
                "tasks": {task_id: task},
                "series": {},
            }
        )
    )
    config = load_config(json_path=store_path)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


def _load(store_file):
    return json.loads(store_file.read_text())


# ---------------------------------------------------------------------------
# Command registration / missing-dependency message
# ---------------------------------------------------------------------------
class TestTuiCommand:
    """Tests for the ``doto tui`` command wiring."""

    def test_tui_command_registered(self):
        assert "tui" in cli.commands

    def test_tui_missing_textual_prints_hint(self, store_file, env, monkeypatch):
        import doxtr_doto.cli.commands.tui as tui_mod

        # Simulate textual being unavailable at command run time.
        import doxtr_doto.cli.tui as tui_pkg

        monkeypatch.setattr(tui_pkg, "TEXTUAL_AVAILABLE", False)
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", str(store_file), "tui"])
        assert result.exit_code == 0
        assert "textual" in result.output.lower()
        # The install hint names the tui extra (wrapping may split the line).
        assert "pip install" in result.output
        assert "tui]" in result.output.replace("\n", "")
        assert tui_mod  # module import sanity


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
class TestData:
    """Tests for the read-only data helpers."""

    def test_gather_tasks_local(self, ctx):
        tasks = data.gather_tasks(ctx, DisplayScope.LOCAL)
        ids = {t["id"] for t in tasks}
        assert ids == {"T-001", "T-002"}
        assert all("_running" in t for t in tasks)

    def test_gather_tasks_marks_running(self, ctx, store_file):
        actions.toggle_timer(ctx, "T-001")
        tasks = data.gather_tasks(ctx, DisplayScope.LOCAL)
        running = {t["id"]: t["_running"] for t in tasks}
        assert running["T-001"] is True
        assert running["T-002"] is False

    def test_live_counters_running_focus(self, ctx):
        actions.toggle_timer(ctx, "T-001")
        work_today, work_running, work_session, focus_seconds = data.live_counters(ctx)
        assert work_running is True
        assert work_today >= 0
        assert work_session >= 0
        assert focus_seconds >= 0

    def test_current_work_session_seconds_open_interval(self):
        from datetime import datetime, timezone

        from doxtr_doto.cli.main import DotoContext

        now = datetime(2024, 1, 1, 10, 0, 30, tzinfo=timezone.utc)

        class _WorkClock:
            worklogs = [
                # Closed interval today - must NOT count toward the session.
                {
                    "started_at": "2024-01-01T09:00:00+00:00",
                    "stopped_at": "2024-01-01T09:30:00+00:00",
                },
                # Open interval - only this one is the current session.
                {"started_at": "2024-01-01T10:00:00+00:00", "stopped_at": None},
            ]

        class _State:
            work_clock = _WorkClock()

        class _GlobalStore:
            def load(self):
                return _State()

        ctx = object.__new__(DotoContext)
        ctx.global_store = _GlobalStore()
        # Only the open interval's 30s counts, not the closed 30-minute one.
        assert data.current_work_session_seconds(ctx, now=now) == 30

    def test_current_work_session_seconds_no_open_session(self):
        from datetime import datetime, timezone

        from doxtr_doto.cli.main import DotoContext

        now = datetime(2024, 1, 1, 10, 0, 30, tzinfo=timezone.utc)

        class _WorkClock:
            worklogs = [
                {
                    "started_at": "2024-01-01T09:00:00+00:00",
                    "stopped_at": "2024-01-01T09:30:00+00:00",
                },
            ]

        class _State:
            work_clock = _WorkClock()

        class _GlobalStore:
            def load(self):
                return _State()

        ctx = object.__new__(DotoContext)
        ctx.global_store = _GlobalStore()
        assert data.current_work_session_seconds(ctx, now=now) == 0

    def test_gather_tasks_global_namespaces_colliding_base(self, ctx, store_file, tmp_path):
        # Two repos share the ``T`` base prefix, so GLOBAL scope namespaces the
        # whole colliding group to ``repo#id``.
        from doxtr_doto.cli.repo_registry import RepoRegistry

        sibling = tmp_path / "repoB" / ".doto" / "tasks.json"
        sibling.parent.mkdir(parents=True)
        sibling.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"T-010": {"title": "sibling", "status": "open"}},
                    "series": {},
                }
            )
        )
        RepoRegistry(ctx.global_store).rescan(tmp_path)
        tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)
        assert tasks  # both repos aggregated
        # The shared ``T`` base prefix forces every ``T`` task to ``repo#id``.
        assert all("#" in t["id"] for t in tasks)

    def test_gather_tasks_global_shortens_unique_base(self, ctx, store_file):
        # With only the current repo registered, every base prefix is unique,
        # so GLOBAL scope keeps the bare local ids.
        from doxtr_doto.cli.repo_registry import RepoRegistry

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)
        assert tasks
        assert {t["id"] for t in tasks} == {"T-001", "T-002"}
        # Resolution tags survive the shortening.
        assert all(t["_repo"] and t["_local_id"] for t in tasks)

    def test_session_intervals_empty(self):
        assert data.session_intervals(None) == []
        assert data.session_intervals({"worklogs": []}) == []

    def test_session_intervals_open(self, ctx, store_file):
        actions.toggle_timer(ctx, "T-001")
        task = ctx.store.get_task("T-001")
        intervals = data.session_intervals(task)
        assert len(intervals) == 1
        # Open interval -> is_open True.
        assert intervals[0][3] is True

    def test_task_total_seconds_none_or_empty(self):
        assert data.task_total_seconds(None) == 0
        assert data.task_total_seconds({}) == 0
        assert data.task_total_seconds({"worklogs": []}) == 0

    def test_task_total_seconds_sums_all_intervals(self):
        from datetime import datetime, timezone

        # Two closed intervals (30s + 90s) plus one open interval counted to
        # ``now`` (60s) -> 180s total across all worklogs.
        task = {
            "worklogs": [
                {
                    "started_at": "2024-01-01T09:00:00+00:00",
                    "stopped_at": "2024-01-01T09:00:30+00:00",
                },
                {
                    "started_at": "2024-01-01T10:00:00+00:00",
                    "stopped_at": "2024-01-01T10:01:30+00:00",
                },
                {
                    "started_at": "2024-01-01T11:00:00+00:00",
                    "stopped_at": None,
                },
            ]
        }
        now = datetime(2024, 1, 1, 11, 1, 0, tzinfo=timezone.utc)
        assert data.task_total_seconds(task, now=now) == 30 + 90 + 60


class TestGatherAndRepoFilter:
    """Integration tests for gather_tasks + the repository filter.

    Exercise the real :func:`doxtr_doto.cli.tui.data.gather_tasks` across two
    registered repositories and the pure
    :func:`doxtr_doto.cli.tui.filtersort.apply_filters` repo filter together,
    covering the three documented scopes: LOCAL (current repo only), GLOBAL +
    no repo selected (all repos), and GLOBAL + selected repos (only those).
    """

    def _two_repo_ctx(self, tmp_path, env):
        """Return a ctx wired to repoA with a sibling repoB, both registered."""
        from doxtr_doto.cli.repo_registry import RepoRegistry

        root = tmp_path / "workspace"
        for name, task_id in (("repoA", "A-001"), ("repoB", "B-001")):
            store_path = root / name / ".doto" / "tasks.json"
            store_path.parent.mkdir(parents=True)
            store_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "updated": "2024-01-01T00:00:00",
                        "tasks": {
                            task_id: {
                                "title": f"{name} task",
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
        config = load_config(json_path=root / "repoA" / ".doto" / "tasks.json")
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(ctx.global_store).rescan(root)
        return ctx

    def test_local_scope_shows_current_repo_only(self, tmp_path, env):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs, apply_filters

        ctx = self._two_repo_ctx(tmp_path, env)
        tasks = data.gather_tasks(ctx, DisplayScope.LOCAL)
        # LOCAL gathers only the current repo (repoA's store), tagged with the
        # current repo name derived from config.source_dir. The repo filter is
        # inert in LOCAL: applying it leaves the single gathered repo intact.
        current = data.current_repo_name(ctx)
        assert {t["_repo"] for t in tasks} == {current}
        assert [t["id"] for t in tasks] == ["A-001"]
        filtered = apply_filters(tasks, ViewPrefs())
        assert {t["_repo"] for t in filtered} == {current}

    def test_global_no_selection_shows_all_repos(self, tmp_path, env):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs, apply_filters

        ctx = self._two_repo_ctx(tmp_path, env)
        tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)
        # GLOBAL aggregates both repos; empty repo_filter keeps everything.
        filtered = apply_filters(tasks, ViewPrefs())
        assert {t["_repo"] for t in filtered} == {"repoA", "repoB"}

    def test_global_selected_shows_only_selected(self, tmp_path, env):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs, apply_filters

        ctx = self._two_repo_ctx(tmp_path, env)
        tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)
        filtered = apply_filters(tasks, ViewPrefs(repo_filter=("repoB",)))
        # Only the selected repo's tasks survive.
        assert {t["_repo"] for t in filtered} == {"repoB"}
        assert [t["_repo"] for t in filtered] == ["repoB"]

    def test_foreign_unique_base_shows_bare_but_action_ref_resolves(self, tmp_path, env):
        # Regression: in GLOBAL scope a FOREIGN repo's task whose base prefix
        # is unique in the view is shown with a BARE display id (per-view
        # shortening), but its ACTION ref must stay canonical ``repo#id`` so
        # start/stop/focus/complete resolve to the foreign repo's store rather
        # than the current repo's. repoA uses base ``A`` and repoB uses base
        # ``B``; both bases are unique, so both display ids are bare.
        from doxtr_doto.cli.id_resolver import resolve_task_ref
        from doxtr_doto.cli.tui.app import DotoApp

        ctx = self._two_repo_ctx(tmp_path, env)
        tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)
        by_repo = {t["_repo"]: t for t in tasks}
        foreign = by_repo["repoB"]
        # Display id is shortened to the bare local id (no ``repo#`` prefix).
        assert foreign["id"] == "B-001"
        assert "#" not in foreign["id"]
        # Resolution tags are preserved so the canonical ref can be rebuilt.
        assert foreign["_repo"] == "repoB"
        assert foreign["_local_id"] == "B-001"

        # The TUI builds the action ref from _repo/_local_id, not the display
        # id. That canonical ref resolves to repoB's store (the owning repo).
        app = DotoApp(ctx)
        app._tasks = tasks
        action_ref = app._action_ref(foreign["id"])
        assert action_ref == "repoB#B-001"
        resolved = resolve_task_ref(ctx, action_ref)
        assert resolved is not None
        assert resolved.repo == "repoB"
        assert resolved.task_id == "B-001"
        assert resolved.store.get_task("B-001") is not None

        # The bare display id would have misresolved away from the owning
        # repo (to the current working directory's store, not repoB), which
        # has no ``B-001`` — proving why the canonical ref is required.
        mis = resolve_task_ref(ctx, foreign["id"])
        assert mis is not None
        assert mis.repo != "repoB"
        assert mis.store.get_task("B-001") is None


class TestCrossRepoSuggestions:
    """known_assignee_names / known_tag_names aggregate across all repos.

    The known-names memory store is per-repo (next to each repo's
    ``tasks.json``), so the TUI suggestion lists must gather candidates from
    every registered repository - not only the current one - or the tags /
    assignee autocomplete would offer only the current repo's values (the
    reported bug). These tests wire a current repo (repoA) with a sibling
    (repoB) that carries distinct tags / assignees both *on tasks* and in its
    *memory store*, and assert both sources from both repos are offered.
    """

    def _two_repo_ctx(self, tmp_path, env):
        """Return a ctx on repoA with a sibling repoB; both have tags+assignee."""
        from doxtr_doto.cli import known_names
        from doxtr_doto.cli.repo_registry import RepoRegistry

        root = tmp_path / "workspace"
        spec = {
            "repoA": ("A-001", "alice", ["alpha"]),
            "repoB": ("B-001", "bob", ["beta"]),
        }
        for name, (task_id, assignee, tags) in spec.items():
            store_path = root / name / ".doto" / "tasks.json"
            store_path.parent.mkdir(parents=True)
            store_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "updated": "2024-01-01T00:00:00",
                        "tasks": {
                            task_id: {
                                "title": f"{name} task",
                                "status": "open",
                                "priority": "medium",
                                "assignee": assignee,
                                "tags": tags,
                                "worklogs": [],
                            }
                        },
                        "series": {},
                    }
                )
            )
            # Memory-store-only values (never used on any task) prove the
            # per-repo known_names.json of a sibling is also read.
            kn_path = store_path.parent / "known_names.json"
            known_names.add_assignee(f"{name}-memory-person", path=kn_path)
            known_names.add_tag(f"{name}-memory-tag", path=kn_path)
        config = load_config(json_path=root / "repoA" / ".doto" / "tasks.json")
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(ctx.global_store).rescan(root)
        return ctx

    def test_known_tag_names_span_all_repos(self, tmp_path, env):
        from doxtr_doto.cli.tui.app import known_tag_names

        ctx = self._two_repo_ctx(tmp_path, env)
        tags = known_tag_names(ctx)
        # Task tags from BOTH repos.
        assert "alpha" in tags
        assert "beta" in tags
        # Memory-store tags from BOTH repos.
        assert "repoA-memory-tag" in tags
        assert "repoB-memory-tag" in tags

    def test_known_assignee_names_span_all_repos(self, tmp_path, env):
        from doxtr_doto.cli.tui.app import known_assignee_names

        ctx = self._two_repo_ctx(tmp_path, env)
        assignees = known_assignee_names(ctx)
        assert "alice" in assignees
        assert "bob" in assignees
        assert "repoA-memory-person" in assignees
        assert "repoB-memory-person" in assignees

    def test_suggestions_deduplicated_case_insensitively(self, tmp_path, env):
        from doxtr_doto.cli.tui.app import known_tag_names

        ctx = self._two_repo_ctx(tmp_path, env)
        tags = known_tag_names(ctx)
        # No duplicate once case-folded (the current repo is also in the
        # registry, so it must not be scanned twice).
        lowered = [t.lower() for t in tags]
        assert len(lowered) == len(set(lowered))


# ---------------------------------------------------------------------------
# Actions (route through CLI verb functions)
# ---------------------------------------------------------------------------
class TestActions:
    """Tests for the mutating actions."""

    def test_complete_task(self, ctx, store_file):
        assert actions.complete_task(ctx, "T-001") is True
        assert _load(store_file)["tasks"]["T-001"]["status"] == "done"

    def test_complete_missing(self, ctx):
        assert actions.complete_task(ctx, "T-999") is False

    def test_update_task(self, ctx, store_file):
        assert actions.update_task(ctx, "T-001", {"title": "Edited"}) is True
        task = _load(store_file)["tasks"]["T-001"]
        assert task["title"] == "Edited"

    def test_update_task_multiple_fields(self, ctx, store_file):
        updates = {"priority": "low", "assignee": "alice", "tags": ["x", "y"]}
        assert actions.update_task(ctx, "T-001", updates) is True
        task = _load(store_file)["tasks"]["T-001"]
        assert task["priority"] == "low"
        assert task["assignee"] == "alice"
        assert task["tags"] == ["x", "y"]

    def test_update_task_empty_is_noop(self, ctx, store_file):
        before = _load(store_file)["tasks"]["T-001"]["title"]
        assert actions.update_task(ctx, "T-001", {}) is True
        assert _load(store_file)["tasks"]["T-001"]["title"] == before

    def test_update_task_missing(self, ctx):
        assert actions.update_task(ctx, "T-999", {"title": "x"}) is False

    def test_cycle_status_advances_and_wraps(self, ctx, store_file):
        # Default cycle: open -> in-progress -> blocked -> done -> open.
        assert actions.cycle_status(ctx, "T-001") == "in-progress"
        assert _load(store_file)["tasks"]["T-001"]["status"] == "in-progress"
        assert actions.cycle_status(ctx, "T-001") == "blocked"
        assert actions.cycle_status(ctx, "T-001") == "done"
        assert actions.cycle_status(ctx, "T-001") == "open"

    def test_cycle_status_missing(self, ctx):
        assert actions.cycle_status(ctx, "T-999") is None

    def test_status_cycle_uses_config(self, ctx):
        ctx.config.statuses = ["todo", "doing", "done"]
        assert actions.status_cycle(ctx) == ["todo", "doing", "done"]

    def test_cycle_status_unknown_current_resets_to_first(self, ctx, store_file):
        actions.update_task(ctx, "T-001", {"status": "weird"})
        assert actions.cycle_status(ctx, "T-001") == "open"

    def test_toggle_timer_start_then_stop(self, ctx, store_file):
        assert actions.toggle_timer(ctx, "T-001") == "started"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] is None
        assert actions.toggle_timer(ctx, "T-001") == "stopped"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] is not None

    def test_toggle_timer_missing(self, ctx):
        assert actions.toggle_timer(ctx, "T-999") == "not_found"

    def test_toggle_timer_stop_through_stale_store_preserves_worklog(self, ctx, store_file):
        """Regression: a stale ``ctx.store`` must not clobber disk on stop.

        Reproduces the TUI focus-timer bug directly. The TUI reuses one
        long-lived ``ctx.store`` across key presses, while ``start`` opens the
        worklog through a *freshly resolved* store for the same path. That
        leaves ``ctx.store``'s in-memory cache stale: it still thinks the task
        has no open worklog. Pre-fix, ``stop_focus`` resolved back to the
        stale ``ctx.store`` and its read-modify-write clobbered disk with the
        empty snapshot - silently dropping the open worklog (and its elapsed
        time), so the green focus arrow stayed on and the recorded interval
        was lost. After the fix the reload rebinds to on-disk truth, so the
        worklog is closed in place (interval preserved) and the arrow clears.

        Pre-fix this fails: the dropped worklog leaves ``total == 0`` and an
        open session; with the fix ``total == 1`` and no open session.
        """
        from doxtr_doto.time_tracking import has_open_session, start_session

        # Prime ctx.store's cache the way the live TUI reads tasks at startup.
        ctx.store.get_all_tasks()

        # A different store instance for the same path opens a worklog on A and
        # persists it - exactly what the TUI's freshly resolved start store
        # does while ``ctx.store`` is reused and goes stale.
        from doxtr_doto.cli.json_store import JsonTaskStore as _Store

        other = _Store(store_file)
        task = other.get_task("T-001")
        task["worklogs"] = start_session(task.get("worklogs", []))
        other.update_task("T-001", {"worklogs": task["worklogs"]})
        other.save()

        # Record the active session so ``stop_focus`` resolves it back to the
        # (now stale) ``ctx.store`` for the matching path.
        state = ctx.global_store.load()
        state.active_session = {
            "repo": "repoA",
            "task_id": "T-001",
            "json_path": str(store_file),
        }
        ctx.global_store.save(state)

        # Pressing ``s`` on A must stop it and preserve the recorded interval.
        assert actions.toggle_timer(ctx, "T-001") == "stopped"

        a_worklogs = _load(store_file)["tasks"]["T-001"]["worklogs"]
        # The interval is retained (total == 1), closed in place - not dropped.
        assert len(a_worklogs) == 1
        assert all(w["stopped_at"] is not None for w in a_worklogs)
        task = _Store(store_file).get_task("T-001")
        assert has_open_session(task.get("worklogs", [])) is False
        assert ctx.global_store.load().active_session is None

    def test_toggle_timer_decides_from_disk_not_stale_cache(self, ctx, store_file):
        """Regression: the start-vs-stop decision must read on-disk truth.

        The TUI reuses one long-lived ``ctx.store`` across presses while the
        worklog is opened through a freshly resolved store for the same path,
        so ``ctx.store``'s cache can be stale. Pre-fix, :func:`toggle_timer`
        decided start-vs-stop from that stale cache: with a task that already
        had an open worklog on disk but an empty cached snapshot, it
        misclassified the task as not running and *started* a second focus
        session - leaving two open worklogs (the green focus arrow stuck on,
        unstoppable with a single press). After the fix the decision reload
        sees the open worklog, correctly reports ``"stopped"``, and closes the
        interval in place (preserved, not duplicated).
        """
        from doxtr_doto.time_tracking import has_open_session, start_session

        ctx.store.get_all_tasks()  # prime the cache, then let it go stale
        from doxtr_doto.cli.json_store import JsonTaskStore as _Store

        other = _Store(store_file)
        task = other.get_task("T-001")
        task["worklogs"] = start_session(task.get("worklogs", []))
        other.update_task("T-001", {"worklogs": task["worklogs"]})
        other.save()
        # Record the session so a stop resolves back to the stale ``ctx.store``.
        state = ctx.global_store.load()
        state.active_session = {
            "repo": "repoA",
            "task_id": "T-001",
            "json_path": str(store_file),
        }
        ctx.global_store.save(state)

        # The task is already running on disk, so a press must STOP it (not
        # erroneously start a second session off the stale empty cache).
        assert actions.toggle_timer(ctx, "T-001") == "stopped"

        a_worklogs = _load(store_file)["tasks"]["T-001"]["worklogs"]
        # The single interval is preserved and closed in place - not
        # duplicated into a second open worklog.
        assert len(a_worklogs) == 1
        assert len([w for w in a_worklogs if w["stopped_at"] is None]) == 0
        task = _Store(store_file).get_task("T-001")
        assert has_open_session(task.get("worklogs", [])) is False
        assert ctx.global_store.load().active_session is None

    def test_toggle_timer_restart_global_scope_can_stop(self, tmp_path, env):
        """Regression (GLOBAL/namespaced scope): intervals survive restart+stop.

        The two tasks live in two different repositories, so the TUI drives
        :func:`toggle_timer` with ``repo#id`` references that resolve to
        distinct stores. ``ctx.store`` (the launch repo) is reused across
        presses and goes stale relative to writes made through the freshly
        resolved stores for the same paths. Pre-fix the stale cache clobbered
        the on-disk worklog list on auto-stop/stop, *dropping* intervals - so
        after the sequence PHYS held only one worklog (the earlier interval
        was lost) and a stop could leave the arrow stuck. After the fix every
        interval is preserved: re-starting PHYS leaves two worklogs (the
        auto-stopped first, closed, plus the new open one), and stopping PHYS
        closes the open one in place (still two total), with the active
        session cleared.
        """
        from doxtr_doto.cli.repo_registry import RepoRegistry

        root = tmp_path / "workspace"
        for name, task_id in (("repoPhys", "PHYS-004"), ("repoAuth", "AUTH-001")):
            store_path = root / name / ".doto" / "tasks.json"
            store_path.parent.mkdir(parents=True)
            store_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "updated": "2024-01-01T00:00:00",
                        "tasks": {
                            task_id: {
                                "title": f"{name} task",
                                "status": "open",
                                "priority": "high",
                                "tags": [],
                                "worklogs": [],
                            }
                        },
                        "series": {},
                    }
                )
            )
        config = load_config(json_path=root / "repoPhys" / ".doto" / "tasks.json")
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(ctx.global_store).rescan(root)

        phys = "repoPhys#PHYS-004"
        auth = "repoAuth#AUTH-001"
        phys_store = root / "repoPhys" / ".doto" / "tasks.json"
        auth_store = root / "repoAuth" / ".doto" / "tasks.json"

        # Touch ctx.store so its cache is populated, matching how the live TUI
        # reads the launch repo at startup (this is what made the stale-cache
        # clobber reproducible).
        ctx.store.get_all_tasks()

        assert actions.toggle_timer(ctx, phys) == "started"
        ctx.store.get_all_tasks()
        assert actions.toggle_timer(ctx, auth) == "started"  # auto-stops PHYS
        ctx.store.get_all_tasks()
        assert actions.toggle_timer(ctx, phys) == "started"  # re-start PHYS

        phys_worklogs = _load(phys_store)["tasks"]["PHYS-004"]["worklogs"]
        auth_worklogs = _load(auth_store)["tasks"]["AUTH-001"]["worklogs"]
        # PHYS's first (auto-stopped) interval must survive alongside the new
        # open one: two total, exactly one open. Pre-fix the clobber dropped
        # the first interval, leaving only one total.
        assert len(phys_worklogs) == 2
        assert len([w for w in phys_worklogs if w["stopped_at"] is None]) == 1
        assert len([w for w in auth_worklogs if w["stopped_at"] is None]) == 0

        ctx.store.get_all_tasks()
        assert actions.toggle_timer(ctx, phys) == "stopped"
        phys_worklogs = _load(phys_store)["tasks"]["PHYS-004"]["worklogs"]
        # Stop closes the open interval in place; both intervals are retained.
        assert len(phys_worklogs) == 2
        assert all(w["stopped_at"] is not None for w in phys_worklogs)
        assert ctx.global_store.load().active_session is None

    def test_clock_out(self, ctx, env):
        actions.toggle_timer(ctx, "T-001")  # clocks in work + focus
        assert actions.clock_out(ctx) is True
        # Second clock-out: work clock already stopped.
        assert actions.clock_out(ctx) is False

    def test_add_task(self, ctx, store_file):
        task_id = actions.add_task(ctx, "A new task")
        tasks = _load(store_file)["tasks"]
        assert task_id in tasks
        assert tasks[task_id]["title"] == "A new task"

    def test_add_task_no_repo_preserves_current(self, ctx, store_file):
        """With ``repo=None`` the task lands in the current store (unchanged)."""
        task_id = actions.add_task(ctx, "Current-repo task", repo=None)
        tasks = _load(store_file)["tasks"]
        assert task_id in tasks
        assert tasks[task_id]["title"] == "Current-repo task"

    def test_add_task_explicit_repo_targets_that_store(self, ctx, store_file, tmp_path):
        """An explicit target repo writes to THAT store, not the current one."""
        from doxtr_doto.cli.repo_registry import DiscoveredRepo

        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {},
                    "series": {},
                }
            )
        )
        repo = DiscoveredRepo(name="repoB", path=str(tmp_path / "repoB"))

        before_current = set(_load(store_file)["tasks"])
        task_id = actions.add_task(ctx, "Other-repo task", repo=repo)

        # Written to repoB's store.
        other_tasks = _load(other_store)["tasks"]
        assert task_id in other_tasks
        assert other_tasks[task_id]["title"] == "Other-repo task"
        # With no .doto.toml in the target, the launch config's prefix is used.
        assert task_id.startswith("DOTO-")
        # The current store is untouched.
        assert set(_load(store_file)["tasks"]) == before_current
        assert task_id not in _load(store_file)["tasks"]

    def test_add_task_explicit_repo_uses_that_repos_id_prefix(self, ctx, tmp_path):
        """An explicit target repo's own ``.doto.toml`` drives the id prefix.

        The launch dir's config (``ctx.config``) uses the default ``DOTO``
        prefix. A target repo whose ``.doto.toml`` sets ``id_prefix = "JENS"``
        must have its new task's id generated with ``JENS``, not ``DOTO``.
        """
        from doxtr_doto.cli.repo_registry import DiscoveredRepo

        assert ctx.config.id_prefix == "DOTO"

        repo_root = tmp_path / "repoJ"
        other_store = repo_root / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {},
                    "series": {},
                }
            )
        )
        (repo_root / ".doto.toml").write_text('[doto]\nid_prefix = "JENS"\n')
        repo = DiscoveredRepo(name="repoJ", path=str(repo_root))

        task_id = actions.add_task(ctx, "Prefixed task", repo=repo)

        # Id uses the TARGET repo's prefix, not the launch dir's.
        assert task_id.startswith("JENS-")
        assert not task_id.startswith("DOTO-")
        # And it was written into the target repo's store.
        assert task_id in _load(other_store)["tasks"]

        # A second add sequences off the target store, not the launch store.
        second_id = actions.add_task(ctx, "Second prefixed task", repo=repo)
        assert second_id.startswith("JENS-")
        assert second_id != task_id
        assert second_id in _load(other_store)["tasks"]

    def test_find_task(self, ctx):
        assert actions.find_task(ctx, "T-001")["title"] == "First task"
        assert actions.find_task(ctx, "T-999") is None

    def test_set_parent_same_repo_ok(self, ctx, store_file):
        """A valid parent in the SAME repo returns OK and sets the field."""
        from doxtr_doto.enums import SetParentResult

        result = actions.set_parent(ctx, "T-001", "T-002")
        assert result == SetParentResult.OK
        assert result == "ok"
        assert _load(store_file)["tasks"]["T-001"]["parent"] == "T-002"

    def test_set_parent_clear_removes_parent(self, ctx, store_file):
        """The CLEAR_PARENT sentinel removes an existing parent link."""
        from doxtr_doto.enums import SetParentResult

        # Seed a parent, then clear it with the empty-string sentinel.
        assert actions.set_parent(ctx, "T-001", "T-002") == SetParentResult.OK
        assert _load(store_file)["tasks"]["T-001"]["parent"] == "T-002"
        result = actions.set_parent(ctx, "T-001", actions.CLEAR_PARENT)
        assert result == SetParentResult.CLEARED
        assert result == "cleared"
        # The parent field is now cleared; the former parent is untouched.
        assert _load(store_file)["tasks"]["T-001"]["parent"] is None
        assert _load(store_file)["tasks"]["T-002"].get("parent") is None

    def test_set_parent_clear_on_unparented_is_idempotent(self, ctx, store_file):
        """Clearing a task that has no parent still returns CLEARED (no error)."""
        from doxtr_doto.enums import SetParentResult

        assert _load(store_file)["tasks"]["T-001"].get("parent") is None
        assert actions.set_parent(ctx, "T-001", actions.CLEAR_PARENT) == SetParentResult.CLEARED
        assert _load(store_file)["tasks"]["T-001"]["parent"] is None

    def test_set_parent_clear_unresolvable_child_not_found(self, ctx, store_file):
        """Clearing a bogus child ref returns NOT_FOUND (no clear happens)."""
        from doxtr_doto.enums import SetParentResult

        assert actions.set_parent(ctx, "T-999", actions.CLEAR_PARENT) == SetParentResult.NOT_FOUND

    def test_set_parent_unresolvable_ref_not_found(self, ctx, store_file):
        """A bogus child or parent ref returns NOT_FOUND and writes nothing."""
        from doxtr_doto.enums import SetParentResult

        assert actions.set_parent(ctx, "T-999", "T-002") == SetParentResult.NOT_FOUND
        assert actions.set_parent(ctx, "T-001", "T-999") == SetParentResult.NOT_FOUND
        # No parent link was written on either real task.
        tasks = _load(store_file)["tasks"]
        assert tasks["T-001"].get("parent") is None
        assert tasks["T-002"].get("parent") is None

    def test_set_parent_cross_repo_rejected(self, tmp_path, env, store_file):
        """A parent in a DIFFERENT repo returns CROSS_REPO and writes nothing."""
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.enums import SetParentResult

        # Sibling repoB (with task B-001) registered alongside the ctx repo.
        other_root = tmp_path / "repoB"
        other_store = other_root / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"B-001": {"title": "Other", "status": "open", "worklogs": []}},
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_file)
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(ctx.global_store).rescan(tmp_path)

        result = actions.set_parent(ctx, "T-001", "repoB#B-001")
        assert result == SetParentResult.CROSS_REPO
        assert _load(store_file)["tasks"]["T-001"].get("parent") is None

    def _two_repo_ctx(self, tmp_path, store_file):
        """Build a ctx for the current repo with a sibling ``repoB`` registered.

        Mirrors :meth:`test_set_parent_cross_repo_rejected`'s fixture so the
        cross-repo *dependency* guard can be exercised the same way.
        """
        from doxtr_doto.cli.repo_registry import RepoRegistry

        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"B-001": {"title": "Other", "status": "open", "worklogs": []}},
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_file)
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(ctx.global_store).rescan(tmp_path)
        return ctx

    def test_update_cross_repo_dependency_rejected(self, tmp_path, env, store_file):
        """A ``depends_on`` entry in a DIFFERENT repo is rejected on update."""
        from doxtr_doto.exceptions import DotoValidationError

        ctx = self._two_repo_ctx(tmp_path, store_file)
        with pytest.raises(DotoValidationError, match="Cross-repo dependencies"):
            actions.update_task(ctx, "T-001", {"depends_on": ["repoB#B-001"]})
        # Nothing was written.
        assert _load(store_file)["tasks"]["T-001"].get("depends_on") in (None, [])

    def test_update_same_repo_dependency_ok(self, tmp_path, env, store_file):
        """A bare / same-repo ``depends_on`` entry is accepted on update."""
        ctx = self._two_repo_ctx(tmp_path, store_file)
        assert actions.update_task(ctx, "T-001", {"depends_on": ["T-002"]}) is True
        assert _load(store_file)["tasks"]["T-001"]["depends_on"] == ["T-002"]

    def test_add_cross_repo_dependency_rejected(self, tmp_path, env, store_file):
        """A ``depends_on`` entry in a DIFFERENT repo is rejected on add."""
        from doxtr_doto.exceptions import DotoValidationError

        ctx = self._two_repo_ctx(tmp_path, store_file)
        before = set(_load(store_file)["tasks"].keys())
        with pytest.raises(DotoValidationError, match="Cross-repo dependencies"):
            actions.add_task(ctx, "New task", depends_on="repoB#B-001")
        # The task was not persisted (the guard runs before the store write).
        assert set(_load(store_file)["tasks"].keys()) == before

    def test_cross_repo_deps_helper(self, tmp_path, env, store_file):
        """The pure cross_repo_deps helper flags only the out-of-repo refs."""
        from doxtr_doto.cli.id_resolver import cross_repo_deps

        ctx = self._two_repo_ctx(tmp_path, store_file)
        # Bare ids and this repo's own namespaced ref are intra-repo; only the
        # repoB ref and an unknown repo are flagged.
        deps = ["T-002", "repoB#B-001", "ghost-repo#X-1"]
        offending = cross_repo_deps(ctx, ctx.store, deps)
        assert offending == ["repoB#B-001", "ghost-repo#X-1"]

    def test_set_parent_self_is_cycle(self, ctx, store_file):
        """Parenting a task to itself returns CYCLE and writes nothing."""
        from doxtr_doto.enums import SetParentResult

        assert actions.set_parent(ctx, "T-001", "T-001") == SetParentResult.CYCLE
        assert _load(store_file)["tasks"]["T-001"].get("parent") is None

    def test_set_parent_indirect_cycle_rejected(self, ctx, store_file):
        """Seed A.parent=B, then set B.parent=A -> CYCLE (no write)."""
        from doxtr_doto.enums import SetParentResult

        # T-001's parent is T-002; now try to parent T-002 under T-001.
        assert actions.set_parent(ctx, "T-001", "T-002") == SetParentResult.OK
        assert actions.set_parent(ctx, "T-002", "T-001") == SetParentResult.CYCLE
        # The second (rejected) assignment left T-002 unparented.
        assert _load(store_file)["tasks"]["T-002"].get("parent") is None

    def test_rescan_repos(self, ctx, store_file):
        count = actions.rescan_repos(ctx, start_dir=store_file.parent.parent.parent)
        assert count >= 1


# ---------------------------------------------------------------------------
# App / Pilot
# ---------------------------------------------------------------------------
def _run(coro):
    """Run an async pilot coroutine on a fresh event loop.

    The project does not depend on ``pytest-asyncio``; Textual's
    :meth:`App.run_test` is async, so each test body is an async closure
    executed here via :func:`asyncio.run`.
    """
    return asyncio.run(coro)


class TestTaskTimeLine:
    """Unit tests for the top-right elapsed-time display (pure classmethod)."""

    def test_shows_day_total_session_and_task_total(self):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        # work_today=7200 (2h), session=3661 (1h01m01s), task total=125 (2m05s)
        rendered = TaskTimeLine.format_times(7200, 3661, True, "T-001", 125)
        assert "Work:" in rendered
        assert "2h00m00s" in rendered  # accumulated day total
        assert "(1h01m01s)" in rendered  # current session in parentheses
        assert "T-001:" in rendered
        assert "2m05s" in rendered  # 125s task total

    def test_no_open_session_omits_parenthetical(self):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        # No session open: show the day total but no parenthetical session.
        rendered = TaskTimeLine.format_times(3600, 0, False, "T-001", 0)
        assert "Work:" in rendered
        assert "1h00m00s" in rendered  # day total still shown
        assert "(" not in rendered  # no current-session parenthetical

    def test_no_task_selected_shows_placeholder(self):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        rendered = TaskTimeLine.format_times(0, 0, False, None, 0)
        assert "Work:" in rendered
        assert "Task: -" in rendered

    def test_running_session_differs_from_stopped(self):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        running = TaskTimeLine.format_times(100, 10, True, "T-001", 0)
        stopped = TaskTimeLine.format_times(100, 10, False, "T-001", 0)
        # Running vs stopped use different styling markup.
        assert running != stopped


class TestEditDueParsing:
    """Unit tests for the edit dialog's due-date parsing (no rendering).

    ``EditTaskScreen.parse_due`` reuses the exact ``doto update --due`` parser,
    so these assert the shared absolute/relative/clear/invalid behaviors
    without rendering the modal.
    """

    def test_absolute_date_passthrough(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        assert EditTaskScreen.parse_due("2099-01-15") == "2099-01-15"

    def test_empty_clears_due(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        assert EditTaskScreen.parse_due("") is None
        assert EditTaskScreen.parse_due("   ") is None

    def test_relative_days_resolve_to_iso(self):
        from doxtr_doto.cli.commands.add import parse_relative_date
        from doxtr_doto.cli.tui.app import EditTaskScreen

        # parse_due must reuse the same CLI parser, so the two agree exactly.
        assert EditTaskScreen.parse_due("+7d") == parse_relative_date("+7d")

    def test_invalid_date_raises_valueerror(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        with pytest.raises(ValueError, match="Invalid date"):
            EditTaskScreen.parse_due("not-a-date")


class TestEditEstimateParsing:
    """Unit tests for the edit dialog's estimate parsing (no rendering).

    ``EditTaskScreen.parse_estimate`` reuses the exact ``doto update
    --estimate`` / ``:estimate:`` directive parser
    (:func:`doxtr_doto.date_utils.parse_duration`), so these assert the shared
    compact-duration / clear / invalid behaviors without rendering the modal.
    """

    def test_compact_durations_resolve_to_minutes(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        assert EditTaskScreen.parse_estimate("90m") == 90
        assert EditTaskScreen.parse_estimate("4h") == 240
        assert EditTaskScreen.parse_estimate("1h30m") == 90

    def test_bare_integer_is_minutes(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        assert EditTaskScreen.parse_estimate("45") == 45

    def test_empty_clears_estimate(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        assert EditTaskScreen.parse_estimate("") is None
        assert EditTaskScreen.parse_estimate("   ") is None

    def test_matches_cli_parser(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen
        from doxtr_doto.date_utils import parse_duration

        # parse_estimate must reuse the same parser, so the two agree exactly.
        assert EditTaskScreen.parse_estimate("1h30m") == parse_duration("1h30m")

    def test_invalid_estimate_raises_valueerror(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        with pytest.raises(ValueError, match="Invalid duration"):
            EditTaskScreen.parse_estimate("banana")

    def test_build_fields_renders_stored_estimate(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        # Stored minutes round-trip back to the compact display form.
        fields = EditTaskScreen.build_fields({"id": "T-1", "estimate": 90})
        assert fields["estimate"] == "1h30m"

    def test_build_fields_blank_estimate_when_unset(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        fields = EditTaskScreen.build_fields({"id": "T-1"})
        assert fields["estimate"] == ""


class TestFilterOptions:
    """Unit tests for the word-based option filter (no rendering)."""

    def test_word_prefix_matches_in_progress(self):
        from doxtr_doto.cli.tui.app import filter_options

        statuses = ["open", "in-progress", "blocked", "done"]
        assert filter_options(statuses, "progress") == ["in-progress"]

    def test_single_letter_matches_critical(self):
        from doxtr_doto.cli.tui.app import filter_options

        priorities = ["low", "medium", "high", "critical"]
        assert filter_options(priorities, "c") == ["critical"]

    def test_prefix_within_multi_word(self):
        from doxtr_doto.cli.tui.app import filter_options

        options = ["in-progress", "in review", "done"]
        # "re" matches the leading word of both "in-progress"? No: words are
        # (in, progress) and (in, review). "re" -> only "review".
        assert filter_options(options, "re") == ["in review"]
        # "in" is the shared first word of both multi-word options.
        assert filter_options(options, "in") == ["in-progress", "in review"]

    def test_case_insensitive(self):
        from doxtr_doto.cli.tui.app import filter_options

        assert filter_options(["Critical", "Low"], "CRIT") == ["Critical"]

    def test_no_match_returns_empty(self):
        from doxtr_doto.cli.tui.app import filter_options

        assert filter_options(["open", "done"], "zzz") == []

    def test_empty_query_returns_all(self):
        from doxtr_doto.cli.tui.app import filter_options

        options = ["open", "in-progress"]
        assert filter_options(options, "") == options
        assert filter_options(options, "   ") == options

    def test_returns_options_in_original_order(self):
        from doxtr_doto.cli.tui.app import filter_options

        options = ["blocked", "backlog", "bug"]
        # All start with "b" -> preserved order.
        assert filter_options(options, "b") == ["blocked", "backlog", "bug"]


class TestBuildRepoOptions:
    """Unit tests for the pure add-task repo-option builder (no rendering)."""

    def test_current_repo_listed_first_with_marker(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import build_repo_options

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repos = [DiscoveredRepo(name="repoB", path="/tmp/repoB")]
        options = build_repo_options(repos, current)
        # Current repo is first and labelled with a (current) marker.
        assert options[0] == ("repoA (current)", "/tmp/repoA")
        assert "(current)" in options[0][0]
        # The other repo follows, unmarked.
        assert options[1] == ("repoB", "/tmp/repoB")

    def test_duplicate_current_path_is_deduped(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import build_repo_options

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        # The cache also contains the current repo (same path); it must not be
        # listed twice (dedupe-by-path).
        repos = [
            DiscoveredRepo(name="repoA", path="/tmp/repoA"),
            DiscoveredRepo(name="repoB", path="/tmp/repoB"),
        ]
        options = build_repo_options(repos, current)
        assert options == [
            ("repoA (current)", "/tmp/repoA"),
            ("repoB", "/tmp/repoB"),
        ]

    def test_values_are_repo_paths(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import build_repo_options

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repos = [DiscoveredRepo(name="repoB", path="/tmp/repoB")]
        values = [value for _label, value in build_repo_options(repos, current)]
        assert values == ["/tmp/repoA", "/tmp/repoB"]


class TestAddTaskScreenRepoResolution:
    """Unit tests for :meth:`AddTaskScreen.repo_for_value` (no rendering).

    The screen is constructed directly (not through a running app) so the
    pure value->repo mapping is exercised without the Pilot harness.
    """

    def test_unknown_value_falls_back_to_current(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddTaskScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repos = [DiscoveredRepo(name="repoB", path="/tmp/repoB")]
        screen = AddTaskScreen(repos, current)
        # A path that matches no known repo resolves to the current repo.
        assert screen.repo_for_value("/nonexistent/path") is current

    def test_known_value_resolves_to_matching_repo(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddTaskScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repo_b = DiscoveredRepo(name="repoB", path="/tmp/repoB")
        screen = AddTaskScreen([repo_b], current)
        # A known path resolves to the matching repo, not the current one.
        assert screen.repo_for_value("/tmp/repoB") is repo_b
        # The current repo's own path still resolves to the current repo.
        assert screen.repo_for_value("/tmp/repoA") is current

    def test_screen_accepts_keyword_arguments(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddTaskScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repos = [DiscoveredRepo(name="repoB", path="/tmp/repoB")]
        # A subclass/caller can inject the inputs by keyword (extensibility).
        screen = AddTaskScreen(repos=repos, current=current)
        assert screen.repos is repos
        assert screen.current is current


class TestAddSeriesScreenRepoResolution:
    """Unit tests for :meth:`AddSeriesScreen.repo_for_value` (no rendering).

    The screen is constructed directly (not through a running app) so the pure
    value->repo mapping is exercised without the Pilot harness, mirroring
    :class:`TestAddTaskScreenRepoResolution`.
    """

    def test_unknown_value_falls_back_to_current(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repos = [DiscoveredRepo(name="repoB", path="/tmp/repoB")]
        screen = AddSeriesScreen(repos, current)
        assert screen.repo_for_value("/nonexistent/path") is current

    def test_known_value_resolves_to_matching_repo(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repo_b = DiscoveredRepo(name="repoB", path="/tmp/repoB")
        screen = AddSeriesScreen([repo_b], current)
        assert screen.repo_for_value("/tmp/repoB") is repo_b
        assert screen.repo_for_value("/tmp/repoA") is current

    def test_repo_options_lists_current_first(self):
        from doxtr_doto.cli.repo_registry import DiscoveredRepo
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        current = DiscoveredRepo(name="repoA", path="/tmp/repoA")
        repo_b = DiscoveredRepo(name="repoB", path="/tmp/repoB")
        screen = AddSeriesScreen([repo_b], current)
        options = screen.repo_options()
        # Current repo is listed first, labelled (current).
        assert options[0][1] == "/tmp/repoA"
        assert "(current)" in options[0][0]


class TestKillRing:
    """Unit tests for the pure :class:`KillRing` (no rendering required).

    These exercise the kill-buffer semantics directly rather than only through
    the Pilot TUI, so the empty-kill guard and empty-yank no-op are verified
    even if the integration tests change. (Still inside the textual-gated
    module because ``KillRing`` is defined in ``app.py``, which imports
    textual at module load.)
    """

    def test_kill_stores_text(self):
        from doxtr_doto.cli.tui.app import KillRing

        ring = KillRing()
        ring.kill("hello")
        assert ring.yank() == "hello"

    def test_empty_kill_preserves_buffer(self):
        from doxtr_doto.cli.tui.app import KillRing

        ring = KillRing()
        ring.kill("keep me")
        ring.kill("")  # empty kill must not clobber the buffer
        assert ring.yank() == "keep me"

    def test_latest_kill_replaces_previous(self):
        from doxtr_doto.cli.tui.app import KillRing

        ring = KillRing()
        ring.kill("first")
        ring.kill("second")
        assert ring.yank() == "second"

    def test_yank_empty_when_nothing_killed(self):
        from doxtr_doto.cli.tui.app import KillRing

        assert KillRing().yank() == ""


class TestApp:
    """Pilot-driven tests of the Textual app."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        # Suppress the once-per-day kickstart nudge so these tests exercise
        # the main screen directly (the nudge is covered by TestNudgeModal).
        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        # These tests render the single current repo's tasks; pin LOCAL scope
        # (the app now defaults to GLOBAL, which aggregates only registered
        # repos and would show nothing for an unregistered current repo).
        app.scope = DisplayScope.LOCAL
        return app

    def test_panes_render(self, ctx):
        from doxtr_doto.cli.tui.widgets import (
            RepoTree,
            StatusLine,
            TaskDetails,
            TaskList,
        )

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.query_one(RepoTree) is not None
                assert app.query_one(TaskDetails) is not None
                assert app.query_one(StatusLine) is not None
                table = app.query_one(TaskList)
                assert set(table.row_ids) == {"T-001", "T-002"}

        _run(body())

    def test_navigation_moves_cursor(self, ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("j")
                assert table.selected_id() == "T-002"
                await pilot.press("k")
                assert table.selected_id() == "T-001"

        _run(body())

    def test_space_selects_task(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                await pilot.press("j")  # cursor on T-002
                await pilot.press("space")
                await pilot.pause()
                assert table.selected_ids == {"T-002"}
                # Space no longer completes: T-002 stays open.
                await pilot.press("space")  # deselect
                await pilot.pause()
                assert table.selected_ids == set()

        _run(body())
        # Space never mutates status.
        assert _load(store_file)["tasks"]["T-002"]["status"] == "open"

    def test_d_sets_cursor_task_done(self, ctx, store_file):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("j")  # select cursor T-002
                await pilot.press("d")
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-002"]["status"] == "done"
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_capital_d_cycles_status(self, ctx, store_file):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Cursor on T-001 (open) -> next status is in-progress.
                await pilot.press("D")
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["status"] == "in-progress"

    def test_space_multi_select_then_d_completes_all(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                assert table.selected_ids == {"T-001", "T-002"}
                await pilot.press("d")  # done on all selected
                await pilot.pause()
                # Selection cleared after the bulk operation.
                assert table.selected_ids == set()

        _run(body())
        tasks = _load(store_file)["tasks"]
        assert tasks["T-001"]["status"] == "done"
        assert tasks["T-002"]["status"] == "done"

    def test_edit_modal_opens_and_applies(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                title_input = app.screen.query_one("#edit-title-input", Input)
                title_input.value = "Renamed task"
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["title"] == "Renamed task"

    def test_edit_modal_prepopulates_fields(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                assert app.screen.query_one("#edit-title-input", Input).value == "First task"
                assert app.screen.query_one("#edit-tags", Input).value == "alpha"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_modal_multi_field_apply(self, ctx, store_file):
        from textual.widgets import Input, Select

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                # Clear assignee, set unsorted/duplicate tags, flip status.
                app.screen.query_one("#edit-assignee", Input).value = ""
                app.screen.query_one("#edit-tags", Input).value = "b, a, a"
                app.screen.query_one("#edit-status", Select).value = "blocked"
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        task = _load(store_file)["tasks"]["T-001"]
        assert task["status"] == "blocked"
        assert task["tags"] == ["a", "b"]
        # Assignee cleared to None (store may drop or null the field).
        assert task.get("assignee") in (None, "")

    def test_edit_modal_cancel_is_noop(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["title"] == "First task"

    def test_edit_modal_sets_due_date(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                # Due field starts empty (T-001 has no due date).
                assert app.screen.query_one("#edit-due", Input).value == ""
                app.screen.query_one("#edit-due", Input).value = "2099-01-15"
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        # Persisted to the JSON store via the same path as ``doto update``.
        assert _load(store_file)["tasks"]["T-001"]["due"] == "2099-01-15"

    def test_edit_modal_sets_estimate(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                # Estimate field starts empty (T-001 has no estimate).
                assert app.screen.query_one("#edit-estimate", Input).value == ""
                app.screen.query_one("#edit-estimate", Input).value = "1h30m"
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        # Stored canonically as whole minutes via the same path as
        # ``doto update``.
        assert _load(store_file)["tasks"]["T-001"]["estimate"] == 90

    def test_edit_modal_clears_estimate(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        # Seed T-001 with an estimate so blanking the field must clear it
        # through the collect_updates "new != old" gate (not just set it).
        ctx.store.update_task("T-001", {"estimate": 90})
        ctx.store.save()
        assert _load(store_file)["tasks"]["T-001"]["estimate"] == 90

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                # Pre-populated from the stored estimate in compact form.
                assert app.screen.query_one("#edit-estimate", Input).value == "1h30m"
                # Blank the field to clear the estimate.
                app.screen.query_one("#edit-estimate", Input).value = ""
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        # Cleared through the same path as ``doto update --clear-estimate``.
        assert _load(store_file)["tasks"]["T-001"]["estimate"] is None

    def test_edit_modal_relative_due_date(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.commands.add import parse_relative_date

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                app.screen.query_one("#edit-due", Input).value = "+7d"
                app.screen._submit()
                await pilot.pause()

        _run(body())
        expected = parse_relative_date("+7d")
        assert _load(store_file)["tasks"]["T-001"]["due"] == expected

    def test_edit_modal_invalid_due_keeps_modal_open(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                app.screen.query_one("#edit-due", Input).value = "not-a-date"
                app.screen._submit()
                await pilot.pause()
                # Invalid date -> modal stays open, nothing is dismissed.
                assert isinstance(app.screen, EditTaskScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())
        # Store is untouched: no corrupt due value written.
        assert "due" not in _load(store_file)["tasks"]["T-001"] or (
            _load(store_file)["tasks"]["T-001"].get("due") is None
        )

    def test_edit_modal_clear_due_date(self, ctx, store_file):
        from textual.widgets import Input

        # Give T-001 a due date first, via the same update path.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                due = app.screen.query_one("#edit-due", Input)
                assert due.value == "2099-01-15"  # pre-populated
                due.value = ""  # clear it
                app.screen._submit()
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"].get("due") is None

    def test_edit_title_kill_and_yank(self, ctx, store_file):
        """Ctrl-K kills to end of line in Title; Ctrl-Y yanks it back."""
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                title_input = app.screen.query_one("#edit-title-input", Input)
                title_input.focus()
                await pilot.pause()
                # Cursor after "First" (len 5); kill " task" to end of line.
                title_input.cursor_position = 5
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert title_input.value == "First"
                # Yank the killed text back at the cursor.
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert title_input.value == "First task"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_title_yank_moves_text(self, ctx, store_file):
        """Killed text can be yanked at a different cursor position."""
        from textual.widgets import Input

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                title_input = app.screen.query_one("#edit-title-input", Input)
                title_input.focus()
                await pilot.pause()
                # Kill "First task" entirely from the start.
                title_input.cursor_position = 0
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert title_input.value == ""
                # Type a prefix, then yank the killed text after it.
                title_input.insert_text_at_cursor("Prefix: ")
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert title_input.value == "Prefix: First task"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_title_kill_at_eol_preserves_buffer(self, ctx, store_file):
        """Ctrl-K with nothing to the right keeps the prior kill buffer."""
        from textual.widgets import Input

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                title_input = app.screen.query_one("#edit-title-input", Input)
                title_input.focus()
                await pilot.pause()
                # Kill the whole line, then press Ctrl-K again at EOL.
                title_input.cursor_position = 0
                await pilot.press("ctrl+k")
                await pilot.pause()
                await pilot.press("ctrl+k")  # no-op kill, buffer preserved
                await pilot.pause()
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert title_input.value == "First task"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_kill_title_yank_into_body(self, ctx, store_file):
        """Text killed in Title can be yanked into the Body (shared kill ring)."""
        from textual.widgets import Input, TextArea

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                title_input = app.screen.query_one("#edit-title-input", Input)
                body_area = app.screen.query_one("#edit-body-input", TextArea)
                # Kill the whole Title line.
                title_input.focus()
                await pilot.pause()
                title_input.cursor_position = 0
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert title_input.value == ""
                # Yank it into the (initially empty) Body.
                starting_body = body_area.text
                body_area.focus()
                await pilot.pause()
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert "First task" in body_area.text
                assert body_area.text != starting_body
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_kill_body_yank_into_title(self, ctx, store_file):
        """Text killed in the Body can be yanked back into Title."""
        from textual.widgets import Input, TextArea

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                title_input = app.screen.query_one("#edit-title-input", Input)
                body_area = app.screen.query_one("#edit-body-input", TextArea)
                # Seed and kill a known body line.
                body_area.load_text("body-content")
                body_area.focus()
                await pilot.pause()
                body_area.move_cursor((0, 0))
                await pilot.press("ctrl+k")  # kill "body-content"
                await pilot.pause()
                # Clear Title, then yank the killed body text into it.
                title_input.focus()
                await pilot.pause()
                title_input.value = ""
                title_input.cursor_position = 0
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert title_input.value == "body-content"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_kill_tags_yank_into_assignee(self, ctx, store_file):
        """The shared kill ring spans the Tags and Assignee inputs too."""
        from textual.widgets import Input

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                tags_input = app.screen.query_one("#edit-tags", Input)
                assignee_input = app.screen.query_one("#edit-assignee", Input)
                # Seed and kill the whole Tags value.
                tags_input.focus()
                await pilot.pause()
                tags_input.value = "alpha, beta"
                tags_input.cursor_position = 0
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert tags_input.value == ""
                # Yank it into the (cleared) Assignee field.
                assignee_input.focus()
                await pilot.pause()
                assignee_input.value = ""
                assignee_input.cursor_position = 0
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert assignee_input.value == "alpha, beta"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_body_yank_noop_when_readonly(self, ctx, store_file):
        """KillRingTextArea.action_yank is a no-op on a read-only Body."""
        from textual.widgets import Input, TextArea

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                title_input = app.screen.query_one("#edit-title-input", Input)
                body_area = app.screen.query_one("#edit-body-input", TextArea)
                # Put something in the kill ring from the Title.
                title_input.focus()
                await pilot.pause()
                title_input.cursor_position = 0
                await pilot.press("ctrl+k")
                await pilot.pause()
                # Make the Body read-only, then attempt to yank.
                before = body_area.text
                body_area.read_only = True
                body_area.focus()
                await pilot.pause()
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert body_area.text == before  # unchanged
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_dialog_widget_classes_are_overridable(self, ctx, store_file):
        """A child theme can swap the input/text-area classes via *_class."""
        from textual.widgets import Input, TextArea

        from doxtr_doto.cli.tui.app import (
            EditTaskScreen,
            KillRingInput,
            KillRingTextArea,
        )

        # The seams exist and default to the kill-ring widgets, mirroring
        # select_class. This is the override point a child theme uses.
        assert EditTaskScreen.input_class is KillRingInput
        assert EditTaskScreen.text_area_class is KillRingTextArea

        app = _ThemedApp(ctx)
        app.scope = DisplayScope.LOCAL  # current-repo task; GLOBAL default shows nothing
        # Suppress the kickstart nudge so `e` opens the edit dialog directly.
        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, _ThemedEditScreen)
                # The dialog rendered the child theme's widget subclasses.
                assert isinstance(
                    app.screen.query_one("#edit-title-input", Input),
                    _ThemedInput,
                )
                assert isinstance(app.screen.query_one("#edit-assignee", Input), _ThemedInput)
                assert isinstance(app.screen.query_one("#edit-tags", Input), _ThemedInput)
                assert isinstance(
                    app.screen.query_one("#edit-body-input", TextArea),
                    _ThemedTextArea,
                )
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_modal_body_is_textarea_with_save(self, ctx, store_file):
        from textual.widgets import Button, TextArea

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                # Body widget is a (scrolling, wrapping) TextArea.
                area = app.screen.query_one("#edit-body-input", TextArea)
                assert area.soft_wrap is True
                # Save button is present.
                assert app.screen.query_one("#edit-save", Button) is not None
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_modal_body_textarea_persists(self, ctx, store_file):
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                area = app.screen.query_one("#edit-body-input", TextArea)
                area.text = "line one\nline two"
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditTaskScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["body"] == "line one\nline two"

    def test_edit_body_quick_key_opens_and_persists(self, ctx, store_file):
        """The ``n`` quick key opens the focused body editor and writes the body."""
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import EditBodyScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("n")  # edit body of cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                area = app.screen.query_one("#editbody-input", TextArea)
                assert area.soft_wrap is True
                area.text = "## Notes\n\nSome **markdown** notes."
                app.screen._submit()
                await pilot.pause()
                assert not isinstance(app.screen, EditBodyScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["body"] == "## Notes\n\nSome **markdown** notes."

    def test_edit_body_quick_key_prepopulates_existing_body(self, ctx, store_file):
        """The body editor is pre-filled with the task's current body."""
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import EditBodyScreen

        actions.update_task(ctx, "T-001", {"body": "existing note"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                area = app.screen.query_one("#editbody-input", TextArea)
                assert area.text == "existing note"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_body_quick_key_cancel_is_noop(self, ctx, store_file):
        """Cancelling the body editor leaves the stored body untouched."""
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import EditBodyScreen

        actions.update_task(ctx, "T-001", {"body": "keep me"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                area = app.screen.query_one("#editbody-input", TextArea)
                area.text = "discarded"
                await pilot.press("escape")  # cancel
                await pilot.pause()
                assert not isinstance(app.screen, EditBodyScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["body"] == "keep me"

    def test_edit_body_quick_key_can_clear_body(self, ctx, store_file):
        """Submitting an empty body clears it (empty string is a valid value)."""
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import EditBodyScreen

        actions.update_task(ctx, "T-001", {"body": "remove me"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                area = app.screen.query_one("#editbody-input", TextArea)
                area.text = ""
                app.screen._submit()
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["body"] == ""

    def test_card_viewer_note_key_opens_body_editor(self, ctx, store_file):
        """Pressing ``n`` in the card viewer opens the focused body editor."""
        from textual.widgets import TextArea

        from doxtr_doto.cli.tui.app import CardViewerScreen, EditBodyScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout (Enter opens the card viewer)
                await pilot.pause()
                await pilot.press("enter")  # open card viewer on T-001
                await pilot.pause()
                assert isinstance(app.screen, CardViewerScreen)
                await pilot.press("n")  # viewer -> body editor
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                area = app.screen.query_one("#editbody-input", TextArea)
                area.text = "note from viewer"
                app.screen._submit()
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["body"] == "note from viewer"

    def test_edit_body_modal_width_follows_config(self, ctx, store_file):
        """The body editor width tracks the configured ``tui_modal_width_ratio``."""
        from textual.containers import Vertical

        from doxtr_doto.cli.tui.app import EditBodyScreen

        actions.save_modal_width_ratio(ctx, "1/2")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                assert isinstance(app.screen, EditBodyScreen)
                modal = app.screen.query_one("#editbody-modal", Vertical)
                # 1/2 of a 120-column terminal -> 60 columns (outer box).
                assert modal.outer_size.width == 60
                # Resizing the terminal re-sizes the open modal (1/2 of 200).
                await pilot.resize_terminal(200, 40)
                await pilot.pause()
                assert modal.outer_size.width == 100
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_task_modal_width_follows_config(self, ctx, store_file):
        """The edit-task modal width tracks the configured ratio (3/4 default)."""
        from textual.containers import Vertical

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("e", "e")
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                modal = app.screen.query_one("#edit-modal", Vertical)
                # Default 3/4 of a 120-column terminal -> 90 columns (outer box).
                assert modal.outer_size.width == 90
                # Resizing the terminal re-sizes the open modal (3/4 of 160).
                await pilot.resize_terminal(160, 40)
                await pilot.pause()
                assert modal.outer_size.width == 120
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_width_follows_config(self, ctx, store_file):
        """The card viewer (``Enter``) width tracks the configured ratio."""
        from textual.containers import Vertical

        from doxtr_doto.cli.tui.app import CardViewerScreen

        actions.save_modal_width_ratio(ctx, "1/2")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout (Enter opens the card viewer)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, CardViewerScreen)
                modal = app.screen.query_one("#viewer-modal", Vertical)
                # 1/2 of a 120-column terminal -> 60 columns (outer box).
                assert modal.outer_size.width == 60
                # Resizing the terminal re-sizes the open viewer (1/2 of 200).
                await pilot.resize_terminal(200, 40)
                await pilot.pause()
                assert modal.outer_size.width == 100
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_configure_modal_width_persists_and_applies(self, ctx, store_file):
        """``c m`` configurator persists the ratio and applies it live."""
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import ModalWidthScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("c")
                await pilot.press("m")
                await pilot.pause()
                assert isinstance(app.screen, ModalWidthScreen)
                app.screen.query_one("#modalwidth-input", Input).value = "1/2"
                app.screen.dismiss(app.screen.collect_ratio())
                await pilot.pause()
                assert app.modal_width_ratio == "1/2"

        _run(body())
        assert ctx.global_store.load().tui_modal_width_ratio == "1/2"

    def test_edit_modal_priority_type_to_select(self, ctx, store_file):
        from textual.widgets import Select

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                priority = app.screen.query_one("#edit-priority", Select)
                priority.focus()
                await pilot.pause()
                # "critical" is the only priority word starting with "c" ->
                # typing "c" auto-selects it.
                await pilot.press("c")
                await pilot.pause()
                assert priority.value == "critical"
                app.screen._submit()
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["priority"] == "critical"

    def test_edit_modal_status_type_filters_options(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import EditTaskScreen, FilterableSelect

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "e")  # edit cursor T-001
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                status = app.screen.query_one("#edit-status", FilterableSelect)
                status.focus()
                await pilot.pause()
                # Typing "progress" matches only "in-progress" -> auto-select.
                for ch in "progress":
                    await pilot.press(ch)
                await pilot.pause()
                assert status.value == "in-progress"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_edit_modal_status_narrows_backspace_and_restores(self, ctx):
        """Exercise the multi-match narrow / no-match no-op / backspace / blur
        branches of ``FilterableSelect`` using a shared-prefix option list."""
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.app import FilterableSelect

        options = ["in-progress", "in-review", "done"]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield FilterableSelect(
                    [(o, o) for o in options],
                    value="in-progress",
                    allow_blank=True,
                    id="sel",
                )

        def _offered(sel):
            # The option values currently offered by the Select (excluding the
            # allow_blank sentinel).
            return [value for _label, value in sel._options if value is not sel.NULL]

        app = _Harness()

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                sel = app.query_one("#sel", FilterableSelect)
                sel.focus()
                await pilot.pause()
                # "in" is the shared first word of two options -> narrow, not
                # auto-select. The current value stays selected because it is
                # still among the matches.
                await pilot.press("i")
                await pilot.press("n")
                await pilot.pause()
                assert set(_offered(sel)) == {"in-progress", "in-review"}
                # P1: narrowing preserves the current value when it is still a
                # match (set_options would otherwise reset it to NULL).
                assert sel.value == "in-progress"
                # A non-matching keystroke is a no-op: options stay narrowed,
                # never emptied.
                await pilot.press("z")
                await pilot.pause()
                assert set(_offered(sel)) == {"in-progress", "in-review"}
                assert sel.value == "in-progress"
                # Backspace shortens the buffer ("inz" -> "in"), still narrowed.
                await pilot.press("backspace")
                await pilot.pause()
                assert set(_offered(sel)) == {"in-progress", "in-review"}
                # Backspacing to empty restores the full option list.
                await pilot.press("backspace")
                await pilot.press("backspace")
                await pilot.pause()
                assert set(_offered(sel)) == set(options)
                assert sel.value == "in-progress"
                # Narrow again, then blur -> full list is restored, value kept.
                await pilot.press("i")
                await pilot.press("n")
                await pilot.pause()
                assert set(_offered(sel)) == {"in-progress", "in-review"}
                sel.blur()
                await pilot.pause()
                assert set(_offered(sel)) == set(options)
                assert sel.value == "in-progress"

        _run(body())

    def test_space_multi_select_then_capital_d_cycles_all(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                assert table.selected_ids == {"T-001", "T-002"}
                await pilot.press("D")  # cycle status on all selected
                await pilot.pause()
                assert table.selected_ids == set()

        _run(body())
        tasks = _load(store_file)["tasks"]
        # Both started open -> next status in-progress.
        assert tasks["T-001"]["status"] == "in-progress"
        assert tasks["T-002"]["status"] == "in-progress"

    def test_filter_prunes_stale_selection(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                await pilot.press("space")  # select T-001
                await pilot.pause()
                assert table.selected_ids == {"T-001"}
                # Apply a filter that excludes T-001; rebuild should drop it.
                app.filter_term = "Second"
                app.refresh_tasks()
                await pilot.pause()
                assert table.selected_ids == set()

        _run(body())

    def test_format_marker_distinguishes_selection(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        assert TaskList.format_marker(True) != TaskList.format_marker(False)
        task = {"id": "T-001", "title": "x", "status": "open"}
        assert TaskList.format_row(task, selected=True)[0] == TaskList.format_marker(True)
        assert TaskList.format_row(task, selected=False)[0] == TaskList.format_marker(False)

    def test_build_fields_prepopulates(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        task = {
            "id": "T-001",
            "title": "First task",
            "assignee": "alice",
            "tags": ["a", "b"],
            "due": "2099-01-15",
            "body": "details",
        }
        fields = EditTaskScreen.build_fields(task)
        assert fields["title"] == "First task"
        assert fields["assignee"] == "alice"
        assert fields["tags"] == "a, b"
        assert fields["due"] == "2099-01-15"
        assert fields["body"] == "details"

    def test_build_fields_handles_missing(self):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        fields = EditTaskScreen.build_fields({"id": "T-001"})
        assert fields == {
            "title": "",
            "assignee": "",
            "tags": "",
            "due": "",
            "estimate": "",
            "body": "",
            "raci_responsible": "",
            "raci_accountable": "",
            "raci_consulted": "",
            "raci_informed": "",
        }

    def test_s_toggles_timer(self, ctx, store_file):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("t", "t")  # start on T-001 (time stream)
                await pilot.pause()
                logs = _load(store_file)["tasks"]["T-001"]["worklogs"]
                assert len(logs) == 1 and logs[0]["stopped_at"] is None
                await pilot.press("t", "t")  # stop
                await pilot.pause()
                logs = _load(store_file)["tasks"]["T-001"]["worklogs"]
                assert logs[0]["stopped_at"] is not None

        _run(body())

    def test_O_clocks_out(self, ctx, store_file, env):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("t", "t")  # clock in work + focus (time stream)
                await pilot.pause()
                await pilot.press("t", "o")  # clock out (time stream)
                await pilot.pause()

        _run(body())
        state = ctx.global_store.load()
        assert state.work_clock.worklogs[-1]["stopped_at"] is not None

    def test_g_toggles_scope(self, ctx):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.scope is DisplayScope.LOCAL
                await pilot.press("g")
                assert app.scope is DisplayScope.GLOBAL
                await pilot.press("g")
                assert app.scope is DisplayScope.LOCAL

        _run(body())

    def test_tab_cycles_panes(self, ctx):
        from doxtr_doto.cli.tui.widgets import RepoTree, TaskDetails, TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Starts focused on the task list.
                assert isinstance(app.focused, TaskList)
                await pilot.press("tab")
                assert isinstance(app.focused, TaskDetails)
                await pilot.press("tab")
                assert isinstance(app.focused, RepoTree)
                await pilot.press("tab")
                assert isinstance(app.focused, TaskList)

        _run(body())

    def test_add_modal_creates_task(self, ctx, store_file):
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                before = len(_load(store_file)["tasks"])
                await pilot.press("a")
                await pilot.pause()
                for ch in "Modal task":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return before

        before = _run(body())
        tasks = _load(store_file)["tasks"]
        assert len(tasks) == before + 1
        assert any(t["title"] == "Modal task" for t in tasks.values())

    def test_add_modal_creates_task_in_selected_repo(self, ctx, store_file, tmp_path):
        """Picking a repo in the add modal creates the task in THAT repo."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        # A sibling repo discoverable alongside the current one.
        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {},
                    "series": {},
                }
            )
        )
        # Populate the registry so the selector offers repoB.
        actions.rescan_repos(ctx, start_dir=tmp_path)

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Repo B task":
                    await pilot.press(ch if ch != " " else "space")
                # Point the repo selector at repoB using the screen's own
                # option values (which store ``.resolve()``d paths), so this
                # does not depend on how tmp paths resolve on the platform.
                options = app.screen.repo_options()
                repo_b_value = next(value for label, value in options if label.startswith("repoB"))
                select = app.screen.query_one("#add-repo")
                select.value = repo_b_value
                await pilot.pause()
                title_input = app.screen.query_one("#add-input")
                title_input.focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

        _run(body())
        # Task landed in repoB, not the current repo (repoA).
        other_tasks = _load(other_store)["tasks"]
        assert any(t["title"] == "Repo B task" for t in other_tasks.values())
        current_tasks = _load(store_file)["tasks"]
        assert not any(t["title"] == "Repo B task" for t in current_tasks.values())

    def test_add_modal_single_repo_omits_selector(self, ctx):
        """With only the current repo, the add modal shows no repo selector."""
        from textual.css.query import NoMatches

        from doxtr_doto.cli.tui.app import AddTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                # Single-repo setups create tasks in the current repo without
                # an empty control, so the selector is absent.
                with pytest.raises(NoMatches):
                    app.screen.query_one("#add-repo")
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_add_modal_empty_title_dismisses_without_task(self, ctx, store_file, tmp_path):
        """Submitting a blank/whitespace title cancels: no task, modal gone."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        # A sibling repo so the selector is present (exercises the full modal).
        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {},
                    "series": {},
                }
            )
        )
        actions.rescan_repos(ctx, start_dir=tmp_path)

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                before = len(_load(store_file)["tasks"])
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                # Type only whitespace, then submit.
                await pilot.press("space")
                await pilot.press("space")
                await pilot.press("enter")
                await pilot.pause()
                # The modal was dismissed: no AddTaskScreen on the stack.
                dismissed = not isinstance(app.screen, AddTaskScreen)
                return before, dismissed

        before, dismissed = _run(body())
        assert dismissed
        # No task was created in either store.
        assert len(_load(store_file)["tasks"]) == before
        assert len(_load(other_store)["tasks"]) == 0

    def test_add_modal_cancel_creates_no_task(self, ctx, store_file):
        """Pressing Escape on the add modal creates no task (counts unchanged)."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                before = len(_load(store_file)["tasks"])
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                # Type a title but cancel instead of submitting.
                for ch in "Discarded task":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("escape")
                await pilot.pause()
                dismissed = not isinstance(app.screen, AddTaskScreen)
                return before, dismissed

        before, dismissed = _run(body())
        assert dismissed
        tasks = _load(store_file)["tasks"]
        assert len(tasks) == before
        assert not any(t["title"] == "Discarded task" for t in tasks.values())

    def test_add_task_screen_is_overridable(self, ctx):
        """A child theme can swap the add-task modal via the *_class seam."""
        from doxtr_doto.cli.tui.app import AddTaskScreen, DotoApp

        # The seam exists and defaults to AddTaskScreen, mirroring
        # edit_task_screen_class. This is the override point a child theme uses.
        assert DotoApp.add_task_screen_class is AddTaskScreen

        app = _ThemedAddApp(ctx)
        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, _ThemedAddTaskScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_add_modal_auto_selects_new_task_when_enabled(self, ctx, store_file):
        """With auto-select on (default), the created task becomes selected."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        assert ctx.config.tui_auto_select_new_task is True
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Pre-condition: cursor starts on the first existing task.
                assert app._current_selected_id() == "T-001"
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Freshly added":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return app._current_selected_id()

        selected = _run(body())
        tasks = _load(store_file)["tasks"]
        new_id = next(tid for tid, t in tasks.items() if t["title"] == "Freshly added")
        assert selected == new_id

    def test_add_modal_does_not_force_select_when_disabled(self, ctx, store_file):
        """With auto-select off, the previous cursor selection is kept."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        ctx.config.tui_auto_select_new_task = False
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._current_selected_id() == "T-001"
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Not auto selected":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return app._current_selected_id()

        selected = _run(body())
        # The task was still created ...
        tasks = _load(store_file)["tasks"]
        new_id = next(tid for tid, t in tasks.items() if t["title"] == "Not auto selected")
        # ... but the cursor was NOT force-moved to it; the id-preserving
        # rebuild keeps the previous selection (T-001).
        assert selected == "T-001"
        assert selected != new_id

    def test_add_modal_auto_selects_new_task_in_list_view(self, ctx, store_file):
        """Auto-select also works in an alt-view (list) layout, not just TABLE."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # switch to the list layout
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "List view added":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return app._current_selected_id()

        selected = _run(body())
        tasks = _load(store_file)["tasks"]
        new_id = next(tid for tid, t in tasks.items() if t["title"] == "List view added")
        assert selected == new_id

    def test_add_series_modal_creates_series(self, ctx, store_file):
        """Pressing ``r`` opens the add-series dialog and creates a series."""
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, AddSeriesScreen)
                # Fill the form by setting the input values directly (the
                # pattern field is multi-word so char-by-char typing is
                # fiddly); this still exercises the real submit path.
                app.screen.query_one("#add-series-title").value = "Important Sync Meeting"
                app.screen.query_one("#add-series-pattern").value = "every 2 weeks on monday"
                app.screen.query_one("#add-series-time").value = "16:00"
                app.screen.query_one("#add-series-duration").value = "2h"
                app.screen.query_one("#add-series-from").value = "2026-11-01"
                app.screen.query_one("#add-series-until").value = "2027-10-10"
                await pilot.pause()
                app.screen.query_one("#add-series-save").focus()
                await pilot.press("enter")
                await pilot.pause()

        _run(body())
        data = _load(store_file)
        assert len(data["series"]) == 1
        series = next(iter(data["series"].values()))
        assert series["pattern"]["start_time"] == "16:00"
        assert series["pattern"]["duration_minutes"] == 120
        assert series["start_date"] == "2026-11-01"
        tasks = [t for t in data["tasks"].values() if t.get("series_id")]
        assert tasks
        for task in tasks:
            assert task["due"].endswith("T16:00")
            assert task["estimate"] == 120

    def test_add_series_modal_invalid_keeps_open(self, ctx, store_file):
        """An invalid form keeps the dialog open and creates no series."""
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, AddSeriesScreen)
                # Missing pattern + until -> validation errors, stays open.
                app.screen.query_one("#add-series-title").value = "X"
                await pilot.pause()
                app.screen.query_one("#add-series-save").focus()
                await pilot.press("enter")
                await pilot.pause()
                return isinstance(app.screen, AddSeriesScreen)

        still_open = _run(body())
        assert still_open
        assert _load(store_file)["series"] == {}

    def test_add_series_modal_cancel_creates_nothing(self, ctx, store_file):
        """Escape dismisses the add-series dialog without creating a series."""
        from doxtr_doto.cli.tui.app import AddSeriesScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, AddSeriesScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())
        assert _load(store_file)["series"] == {}

    def test_add_series_screen_is_overridable(self, ctx):
        """A child theme can swap the add-series screen class."""
        from doxtr_doto.cli.tui.app import AddSeriesScreen, DotoApp

        class _ThemedAddSeriesScreen(AddSeriesScreen):
            pass

        class _ThemedApp(DotoApp):
            add_series_screen_class = _ThemedAddSeriesScreen

        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _ThemedApp(ctx)
        app.scope = DisplayScope.LOCAL

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, _ThemedAddSeriesScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_select_task_moves_cursor_to_row_in_local_scope(self, ctx):
        """``select_task`` selects the matching row by id in LOCAL scope."""
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                # Selecting an existing task by its (bare) id moves the cursor.
                selected_second = app.select_task("T-002")
                await pilot.pause()
                selected_first = app.select_task("T-001")
                await pilot.pause()
                # A non-existent id is a no-op that returns False.
                missing = app.select_task("T-999")
                return (
                    selected_second,
                    selected_first,
                    missing,
                    table.selected_id(),
                )

        selected_second, selected_first, missing, final = _run(body())
        assert selected_second is True
        assert selected_first is True
        assert missing is False
        # The last successful selection (T-001) is where the cursor landed.
        assert final == "T-001"

    def test_display_id_for_maps_bare_id_to_namespaced_display_id(self, ctx):
        """GLOBAL scope: the bare ``add_task`` id maps to the ``repo#id`` row.

        The LOCAL ``select_task`` test above exercises the bare-id path where
        display id == local id. This covers the namespaced path:
        :meth:`DotoApp._display_id_for` must resolve the bare local id
        returned by ``add_task`` to the ``repo#id`` *display* id the views key
        their rows on when GLOBAL scope namespaces a colliding base prefix.
        Focused unit test: ``_tasks`` is populated directly with rows carrying
        ``_repo`` / ``_local_id`` and the namespaced display ``id`` (as
        :func:`doxtr_doto.cli.tui.data.gather_tasks` +
        :func:`doxtr_doto.cli.display.apply_scope` produce in GLOBAL scope),
        using the current repo name as the owning repo so the mapping matches
        on ``_repo``.
        """
        from doxtr_doto.cli.tui.app import DotoApp

        app = DotoApp(ctx)
        current = data.current_repo_name(ctx)
        other = "otherRepo"
        assert other != current
        # Two repos share a base prefix, so every display id is namespaced to
        # ``repo#id`` while ``_local_id`` preserves the bare id.
        app._tasks = [
            {"id": f"{current}#T-001", "_repo": current, "_local_id": "T-001"},
            {"id": f"{current}#T-002", "_repo": current, "_local_id": "T-002"},
            {"id": f"{other}#T-010", "_repo": other, "_local_id": "T-010"},
        ]
        # A current-repo bare id maps to its namespaced display id.
        assert app._display_id_for("T-001") == f"{current}#T-001"
        assert app._display_id_for("T-002") == f"{current}#T-002"
        # A foreign repo's bare id has no current-repo row, so it falls back
        # unchanged (it is only resolved against the current repo).
        assert app._display_id_for("T-010") == "T-010"
        # An id with no matching row is returned unchanged (already a display
        # id, or filtered out).
        assert app._display_id_for("T-999") == "T-999"

    def test_select_task_filtered_out_task_is_noop(self, ctx):
        """``select_task`` on an id absent from the visible set is a no-op.

        When the created task is filtered out it has no row in ``_tasks``, so
        :meth:`DotoApp._display_id_for` falls back to the bare id, no view row
        matches, and ``select_task`` returns False without moving the
        selection. This targets the app-level ``select_task`` +
        ``_display_id_for`` fallback (the view-level missing-id case is
        covered by the per-view ``select_id`` tests).
        """
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Move off the default first row so a no-op is observable.
                assert app.select_task("T-002") is True
                await pilot.pause()
                before = table.selected_id()
                # An id not in the visible _tasks set is a no-op.
                result = app.select_task("T-FILTERED-OUT")
                await pilot.pause()
                return result, before, table.selected_id()

        result, before, after = _run(body())
        assert result is False
        # The selection did not move.
        assert before == "T-002"
        assert after == before

    def test_series_next_moves_to_later_occurrence(self, series_ctx):
        """``e n`` moves the selection to the next (due-date-later) occurrence.

        The jump follows occurrence (due-date) order, not id/insertion order:
        from ``S-003`` (earliest, 2026-01-05) ``_move_in_series(1)`` lands on
        ``S-002`` (2026-01-12), proving the step is by due date even though
        ``S-002`` sorts between ``S-001`` and ``S-003`` by id.
        """
        app = self._app(series_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-003") is True
                await pilot.pause()
                app._move_in_series(1)
                await pilot.pause()
                first = app._current_selected_id()
                app._move_in_series(1)
                await pilot.pause()
                return first, app._current_selected_id()

        first, second = _run(body())
        assert first == "S-002"
        assert second == "S-001"

    def test_series_prev_moves_to_earlier_occurrence(self, series_ctx):
        """``e p`` moves the selection to the previous (earlier) occurrence."""
        app = self._app(series_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-001") is True  # latest occurrence
                await pilot.pause()
                app._move_in_series(-1)
                await pilot.pause()
                first = app._current_selected_id()
                app._move_in_series(-1)
                await pilot.pause()
                return first, app._current_selected_id()

        first, second = _run(body())
        assert first == "S-002"
        assert second == "S-003"

    def test_series_next_at_last_occurrence_clamps(self, series_ctx):
        """At the last occurrence ``e n`` clamps (no wrap) and keeps selection."""
        app = self._app(series_ctx)
        notes: list[str] = []
        app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-001") is True  # latest occurrence
                await pilot.pause()
                app._move_in_series(1)
                await pilot.pause()
                return app._current_selected_id()

        final = _run(body())
        # No wrap: selection stays on the last occurrence.
        assert final == "S-001"
        assert any("last occurrence" in n for n in notes)

    def test_series_prev_at_first_occurrence_clamps(self, series_ctx):
        """At the first occurrence ``e p`` clamps (no wrap) and keeps selection."""
        app = self._app(series_ctx)
        notes: list[str] = []
        app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-003") is True  # earliest occurrence
                await pilot.pause()
                app._move_in_series(-1)
                await pilot.pause()
                return app._current_selected_id()

        final = _run(body())
        assert final == "S-003"
        assert any("first occurrence" in n for n in notes)

    def test_series_nav_noop_on_standalone_task(self, series_ctx):
        """A non-series selection is a graceful no-op (no move, no notify)."""
        app = self._app(series_ctx)
        notes: list[str] = []
        app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("T-100") is True  # standalone, no series
                await pilot.pause()
                app._move_in_series(1)
                await pilot.pause()
                return app._current_selected_id()

        final = _run(body())
        assert final == "T-100"
        assert notes == []

    def test_series_nav_end_to_end_via_stream_keys(self, series_ctx):
        """Pressing ``e n`` through the dispatcher jumps to the next occurrence.

        Exercises the full registry -> dispatcher -> ``action_series_next``
        path (the ``e`` Edit domain resolves ``n`` to the ``series_next``
        action only because the selection is a series member).
        """
        app = self._app(series_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-003") is True
                await pilot.pause()
                await pilot.press("e", "n")
                await pilot.pause()
                return app._current_selected_id()

        final = _run(body())
        assert final == "S-002"

    def test_series_nav_entries_only_for_series_members(self, series_ctx):
        """The ``e n`` / ``e p`` entries appear only for a series occurrence.

        Mirrors the ``e E`` / ``e D`` conditional discipline: the Edit domain's
        ``entries_fn`` adds the series-navigation rows when (and only when) the
        selection carries a ``series_id``, so the hint bar and help stay
        correct automatically.
        """
        from doxtr_doto.cli.tui.app import KEYMAP

        app = self._app(series_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # On a series occurrence: the nav entries are present.
                assert app.select_task("S-003") is True
                await pilot.pause()
                member_actions = [e.action for e in KEYMAP["e"].entries_fn(app)]
                # On a standalone task: the nav entries are absent.
                assert app.select_task("T-100") is True
                await pilot.pause()
                standalone_actions = [e.action for e in KEYMAP["e"].entries_fn(app)]
                return member_actions, standalone_actions

        member_actions, standalone_actions = _run(body())
        assert "series_next" in member_actions
        assert "series_prev" in member_actions
        assert "series_next" not in standalone_actions
        assert "series_prev" not in standalone_actions

    def test_series_nav_filtered_out_neighbour_notifies(self, series_ctx):
        """A neighbour hidden by the active filter is a no-op with a notify.

        From the middle occurrence (``S-002``) a filter that matches only its
        own title hides both neighbours. ``_move_in_series(1)`` resolves the
        target (``S-001``, which still exists in the store) but cannot select
        it because it is filtered out of the view: the selection must stay on
        ``S-002`` and a notify containing ``filtered out`` must fire.
        """
        app = self._app(series_ctx)
        notes: list[str] = []
        app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.select_task("S-002") is True  # middle occurrence
                await pilot.pause()
                # Filter to the middle occurrence's title only, hiding the
                # S-001 neighbour that ``e n`` would move to.
                app.filter_term = "second"
                app.refresh_tasks()
                await pilot.pause()
                app._move_in_series(1)
                await pilot.pause()
                return app._current_selected_id()

        final = _run(body())
        assert final == "S-002"
        assert any("filtered out" in n for n in notes)

    def test_filter_narrows_list(self, ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.pause()
                for ch in "First":
                    await pilot.press(ch)
                await pilot.press("enter")
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.row_ids == ["T-001"]

        _run(body())

    def test_view_prefs_popup_opens_and_persists(self, ctx):
        from doxtr_doto.cli.tui.app import ViewPrefsScreen
        from doxtr_doto.enums import SortKey

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # ``F`` opens the filter/sort pop-up (Feature C).
                await pilot.press("F")
                await pilot.pause()
                assert isinstance(app.screen, ViewPrefsScreen)
                # Simulate the user applying a priority sort and dismiss.
                from doxtr_doto.cli.tui.filtersort import ViewPrefs

                app.screen.dismiss(ViewPrefs(sort_key=SortKey.PRIORITY))
                await pilot.pause()
                assert not isinstance(app.screen, ViewPrefsScreen)
                # The chosen sort is stored on the app and persisted (memory).
                assert app.view_prefs.sort_key is SortKey.PRIORITY
                assert ctx.global_store.load().tui_sort_key == "priority"

        _run(body())

    def test_default_scope_is_global(self, ctx):
        from doxtr_doto.cli.tui.app import DotoApp

        # Feature requirement #1: the app defaults to GLOBAL scope.
        assert DotoApp(ctx).scope is DisplayScope.GLOBAL

    def test_view_prefs_screen_repo_selections(self):
        from doxtr_doto.cli.tui.app import ViewPrefsScreen
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # The repo multi-select rows pre-check the repos already in the filter;
        # the prompt and value are both the repo name.
        screen = ViewPrefsScreen(
            ViewPrefs(repo_filter=("web",)),
            tags=[],
            priorities=[],
            repos=["web", "api", "docs"],
        )
        assert screen._repo_selections() == [
            ("web", "web", True),
            ("api", "api", False),
            ("docs", "docs", False),
        ]

    def test_view_prefs_popup_sets_repo_filter(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.app import ViewPrefsScreen
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # Register the current repo so the pop-up offers it in the repo list.
        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("F")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ViewPrefsScreen)
                # Pick the first offered repository in the multi-select and
                # collect the prefs: the repo filter must carry that name.
                repo_name = screen.repos[0]
                from textual.widgets import SelectionList

                sel = screen.query_one("#viewprefs-repos", SelectionList)
                sel.select(repo_name)
                await pilot.pause()
                collected = screen.collect_prefs()
                assert repo_name in collected.repo_filter
                # Apply it and confirm it is stored + persisted.
                screen.dismiss(ViewPrefs(repo_filter=(repo_name,)))
                await pilot.pause()
                assert app.view_prefs.repo_filter == (repo_name,)
                assert ctx.global_store.load().tui_repo_filter == [repo_name]

        _run(body())

    def test_view_prefs_popup_collects_recent_done(self, ctx):
        from doxtr_doto.cli.tui.app import ViewPrefsScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("F")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ViewPrefsScreen)
                from textual.widgets import Checkbox, Input

                # Enable the recent-done filter and set a 5-day window.
                screen.query_one("#viewprefs-recent-done", Checkbox).value = True
                screen.query_one("#viewprefs-recent-done-days", Input).value = "5"
                await pilot.pause()
                collected = screen.collect_prefs()
                assert collected.recent_done_days == 5

        _run(body())

    def test_view_prefs_popup_collects_recent_done_disabled(self, ctx):
        from doxtr_doto.cli.tui.app import ViewPrefsScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("F")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ViewPrefsScreen)
                from textual.widgets import Checkbox

                # Unchecking the recent-done box disables the filter (None).
                screen.query_one("#viewprefs-recent-done", Checkbox).value = False
                await pilot.pause()
                assert screen.collect_prefs().recent_done_days is None

        _run(body())

    def test_repo_tree_leaf_toggles_repo_filter(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.widgets import RepoTree

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)
        # Selecting a repo leaf is a GLOBAL-scope affordance.
        app.scope = DisplayScope.GLOBAL

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.refresh_repos()
                await pilot.pause()
                tree = app.query_one(RepoTree)
                # Find a repository leaf (its node.data carries the repo name).
                leaf = next(
                    node
                    for node in tree.root.children[1].children
                    if isinstance(getattr(node, "data", None), str)
                )
                repo_name = leaf.data
                # Posting the tree's NodeSelected message drives the app's
                # on_tree_node_selected handler (as a real selection would).
                tree.post_message(RepoTree.NodeSelected(leaf))
                await pilot.pause()
                assert repo_name in app.view_prefs.repo_filter
                assert ctx.global_store.load().tui_repo_filter == [repo_name]
                # Selecting it again toggles it back out.
                tree.post_message(RepoTree.NodeSelected(leaf))
                await pilot.pause()
                assert repo_name not in app.view_prefs.repo_filter
                assert ctx.global_store.load().tui_repo_filter is None

        _run(body())

    def test_repo_tree_leaf_toggle_is_noop_in_local_scope(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.widgets import RepoTree

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)
        # In LOCAL scope the repo filter is ignored, so selecting a leaf must
        # NOT mutate or persist ``repo_filter`` (it would be a confusing
        # silent change to a filter the LOCAL view does not honor).
        app.scope = DisplayScope.LOCAL

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.refresh_repos()
                await pilot.pause()
                tree = app.query_one(RepoTree)
                leaf = next(
                    node
                    for node in tree.root.children[1].children
                    if isinstance(getattr(node, "data", None), str)
                )
                tree.post_message(RepoTree.NodeSelected(leaf))
                await pilot.pause()
                assert app.view_prefs.repo_filter == ()
                assert ctx.global_store.load().tui_repo_filter is None

        _run(body())

    def test_view_prefs_screen_class_is_overridable(self, ctx):
        from doxtr_doto.cli.tui.app import DotoApp, ViewPrefsScreen

        # The seam exists and defaults to ViewPrefsScreen, mirroring the other
        # *_screen_class overridable modal seams.
        assert DotoApp.view_prefs_screen_class is ViewPrefsScreen

        class _ThemedViewPrefsScreen(ViewPrefsScreen):
            """Stand-in for a child theme's custom filter/sort pop-up."""

        class _ThemedViewPrefsApp(DotoApp):
            view_prefs_screen_class = _ThemedViewPrefsScreen

        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _ThemedViewPrefsApp(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("F")
                await pilot.pause()
                assert isinstance(app.screen, _ThemedViewPrefsScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_set_parent_single_cursor_task(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import SetParentScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Cursor on T-001; open the set-parent picker (e P).
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                # The search box is focused on open so the user can type to
                # search immediately (no Enter needed to start filtering).
                search = app.screen.query_one("#setparent-search", Input)
                assert app.focused is search
                # Type part of the only other task and submit with Enter, which
                # applies the highlighted candidate (T-002).
                await pilot.press("T", "-", "0", "0", "2")
                await pilot.pause()
                assert app.screen._highlighted_value == "T-002"
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, SetParentScreen)

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["parent"] == "T-002"
        # The parent task itself is unaffected.
        assert _load(store_file)["tasks"]["T-002"].get("parent") is None

    def test_set_parent_clear_via_no_parent_entry(self, ctx, store_file):
        """Choosing the leading "(no parent)" entry removes the parent link."""
        from doxtr_doto.cli.tui import actions as tui_actions
        from doxtr_doto.cli.tui.app import SetParentScreen
        from doxtr_doto.cli.tui.widgets import TaskList

        # Seed T-001 under T-002 first.
        assert actions.set_parent(ctx, "T-001", "T-002") == "ok"

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Put the cursor on T-001 deterministically (tree ordering can
                # vary once it is a child of T-002).
                table = app.query_one(TaskList)
                table.move_cursor(row=table.row_ids.index("T-001"))
                await pilot.pause()
                # Open the picker and pick "(no parent)".
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                app.screen.dismiss(tui_actions.CLEAR_PARENT)
                await pilot.pause()
                assert not isinstance(app.screen, SetParentScreen)
                # Clearing is never remembered as the last parent.
                assert app._last_parent_id != tui_actions.CLEAR_PARENT

        _run(body())
        # The parent link was removed; the former parent is untouched.
        assert _load(store_file)["tasks"]["T-001"]["parent"] is None
        assert _load(store_file)["tasks"]["T-002"].get("parent") is None

    def test_set_parent_multi_selection(self, parent_ctx, parent_store_file):
        from doxtr_doto.cli.tui.app import SetParentScreen
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(parent_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Multi-select T-001 and T-002 as the children.
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                assert table.selected_ids == {"T-001", "T-002"}
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                # The children are excluded from the candidate parents, so
                # only T-003 remains selectable (plus the leading "(no parent)"
                # clear entry).
                values = {value for _label, value in app.screen.candidates}
                assert values == {actions.CLEAR_PARENT, "T-003"}
                app.screen.dismiss("T-003")
                await pilot.pause()
                # Selection cleared after the bulk operation.
                assert table.selected_ids == set()

        _run(body())
        tasks = _load(parent_store_file)["tasks"]
        assert tasks["T-001"]["parent"] == "T-003"
        assert tasks["T-002"]["parent"] == "T-003"

    def test_set_parent_remembers_last_parent(self, parent_ctx, parent_store_file):
        from doxtr_doto.cli.tui.app import SetParentScreen

        app = self._app(parent_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # First assignment: T-001's parent -> T-003.
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                app.screen.dismiss("T-003")
                await pilot.pause()
                assert app._last_parent_id == "T-003"
                # Reopen on a different cursor row: the picker pre-highlights
                # the remembered parent (T-003) in its candidate list.
                await pilot.press("j")  # cursor -> T-002
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                assert app.screen.default == "T-003"
                assert app.screen._highlighted_value == "T-003"
                app.screen.dismiss(None)  # cancel, leaving memory intact
                await pilot.pause()

        _run(body())
        tasks = _load(parent_store_file)["tasks"]
        assert tasks["T-001"]["parent"] == "T-003"
        # Cancelled second assignment leaves T-002 unparented.
        assert tasks["T-002"].get("parent") is None

    def test_set_parent_candidates_exclude_children(self, parent_ctx, parent_store_file):
        from doxtr_doto.cli.tui.app import SetParentScreen

        app = self._app(parent_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Single cursor task T-001 is the child; it must not appear as
                # its own candidate parent.
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                values = {value for _label, value in app.screen.candidates}
                assert "T-001" not in values
                # Other visible tasks plus the leading "(no parent)" clear entry.
                assert values == {actions.CLEAR_PARENT, "T-002", "T-003"}
                app.screen.dismiss(None)
                await pilot.pause()

        _run(body())

    def test_set_parent_cycle_rejected_through_chosen(self, parent_ctx, parent_store_file):
        """Picking a descendant as parent is skipped and warns (cycle path).

        Seeds T-002.parent = T-001, then with T-001 as the child selects
        T-002 as its parent. That is a cycle, so ``_chosen`` skips it: T-001
        stays unparented, the store is unchanged, and the
        "Could not set parent (self/cycle or cross-repo)." warning fires.
        """
        from doxtr_doto.cli.tui.app import SetParentScreen

        app = self._app(parent_ctx)
        notes: list[str] = []

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Seed T-002 under T-001 via the real action.
                assert actions.set_parent(parent_ctx, "T-002", "T-001") == "ok"
                app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]
                # Cursor on T-001 (the child); pick its descendant T-002 as parent.
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                app.screen.dismiss("T-002")
                await pilot.pause()

        _run(body())
        tasks = _load(parent_store_file)["tasks"]
        # The rejected assignment left T-001 unparented; T-002 keeps its seed.
        assert tasks["T-001"].get("parent") is None
        assert tasks["T-002"]["parent"] == "T-001"
        # The cycle/cross-repo warning branch fired.
        assert any("Could not set parent" in msg for msg in notes)

    def test_set_parent_screen_class_is_overridable(self, ctx):
        from doxtr_doto.cli.tui.app import DotoApp, SetParentScreen

        # The seam exists and defaults to SetParentScreen, mirroring the other
        # *_screen_class overridable modal seams.
        assert DotoApp.set_parent_screen_class is SetParentScreen

        class _ThemedSetParentScreen(SetParentScreen):
            """Stand-in for a child theme's custom parent picker."""

        class _ThemedSetParentApp(DotoApp):
            set_parent_screen_class = _ThemedSetParentScreen

        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _ThemedSetParentApp(ctx)
        app.scope = DisplayScope.LOCAL

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, _ThemedSetParentScreen)
                app.screen.dismiss(None)
                await pilot.pause()

        _run(body())

    def test_set_parent_select_class_is_overridable(self, ctx):
        from doxtr_doto.cli.tui.app import FilterableSelect, SetParentScreen

        # The select_class seam defaults to FilterableSelect, mirroring
        # ViewPrefsScreen / EditTaskScreen.
        assert SetParentScreen.select_class is FilterableSelect

        class _ThemedSelect(FilterableSelect):
            """Stand-in for a child theme's custom parent-picker dropdown."""

        class _ThemedSetParentScreen(SetParentScreen):
            select_class = _ThemedSelect

        screen = _ThemedSetParentScreen([("T-002  Second task", "T-002")])
        assert screen.select_class is _ThemedSelect

    def test_set_parent_type_to_search_filters_immediately(self, parent_ctx, parent_store_file):
        """Typing in the set-parent picker filters the list without pressing
        Enter first: the search box is focused on open and each keystroke
        re-filters the visible candidate list live."""
        from textual.widgets import Input, OptionList

        from doxtr_doto.cli.tui.app import SetParentScreen

        app = self._app(parent_ctx)

        def listed(option_list):
            return [option_list.get_option_at_index(i).id for i in range(option_list.option_count)]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Cursor on T-001; open the picker. Candidates are T-002/T-003.
                await pilot.press("e", "P")
                await pilot.pause()
                assert isinstance(app.screen, SetParentScreen)
                # The search box is focused immediately -> no Enter needed.
                search = app.screen.query_one("#setparent-search", Input)
                assert app.focused is search
                option_list = app.screen.query_one("#setparent-list", OptionList)
                # Full list before typing (plus the leading "(no parent)" entry).
                assert set(listed(option_list)) == {
                    actions.CLEAR_PARENT,
                    "T-002",
                    "T-003",
                }
                # Typing narrows the visible list live (no Enter needed); the
                # "(no parent)" entry drops out since it does not match.
                await pilot.press("T", "-", "0", "0", "3")
                await pilot.pause()
                assert listed(option_list) == ["T-003"]
                assert app.screen._highlighted_value == "T-003"
                app.screen.dismiss(None)
                await pilot.pause()

        _run(body())

    def test_help_modal_opens_and_closes(self, ctx):
        from doxtr_doto.cli.tui.app import HelpScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                await pilot.pause()
                assert isinstance(app.screen, HelpScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, HelpScreen)

        _run(body())

    def test_status_line_updates(self, ctx):
        from doxtr_doto.cli.tui.widgets import StatusLine

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("t", "t")  # start timer -> work clock running
                await pilot.pause()
                app.refresh_counters()
                status = app.query_one(StatusLine)
                rendered = str(status.render())
                assert "Work" in rendered
                assert "Focus" in rendered

        _run(body())

    def test_refresh_counters_noop_without_status_line(self, ctx):
        """The interval-driven counter refresh is a no-op if StatusLine is gone.

        ``refresh_counters`` is driven by a recurring timer that can fire while
        the app is mounting / tearing down (or while a modal is pushed), when
        the status line is not queryable. It must not raise ``NoMatches``.
        """
        from doxtr_doto.cli.tui.widgets import StatusLine

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Remove the status line to simulate the teardown/startup gap.
                app.query_one(StatusLine).remove()
                await pilot.pause()
                # Must not raise even though the widget is absent.
                app.refresh_counters()
                await pilot.pause()

        _run(body())

    def test_refresh_counters_reasserts_terminal_title(self, ctx):
        """The counter timer re-emits the terminal title each tick.

        Some terminals (e.g. the VS Code integrated terminal) reset the tab
        label to the foreground process name after process detection, so a
        title set only once at mount is clobbered. ``refresh_counters`` must
        therefore re-assert :data:`TERMINAL_TITLE` on every tick, in addition
        to the one-time write in ``on_mount``.
        """
        from doxtr_doto.cli.tui import TERMINAL_TITLE

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                writes: list[str] = []
                driver = app._driver
                assert driver is not None
                driver.write = writes.append  # type: ignore[method-assign]
                app.refresh_counters()
                await pilot.pause()
                assert any(f"\033]0;{TERMINAL_TITLE}\007" in chunk for chunk in writes)

        _run(body())

    def test_task_time_line_shows_current_task_total(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("t", "t")  # start a focus timer on T-001
                await pilot.pause()
                app.refresh_task_time()
                time_line = app.query_one(TaskTimeLine)
                rendered = str(time_line.render())
                assert "Work:" in rendered
                # The current (highlighted) task's id is shown with its total.
                assert "T-001" in rendered

        _run(body())

    def test_task_time_line_updates_on_navigation(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                time_line = app.query_one(TaskTimeLine)
                assert "T-001" in str(time_line.render())
                await pilot.press("j")  # move cursor to T-002
                await pilot.pause()
                assert "T-002" in str(time_line.render())

        _run(body())

    def test_refresh_task_time_noop_without_widget(self, ctx):
        """The task-time refresh is a benign no-op if the widget is absent."""
        from doxtr_doto.cli.tui.widgets import TaskTimeLine

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one(TaskTimeLine).remove()
                await pilot.pause()
                # Must not raise even though the widget is absent.
                app.refresh_task_time()
                await pilot.pause()

        _run(body())


class TestBracketHighlightLiveTheme:
    """The live app resolves the theme accent and tracks theme changes.

    ``refresh_accent_highlights`` publishes the current theme's accent onto the
    overridable ``TitleHighlight.BRACKET_HIGHLIGHT_STYLE`` class attribute on
    mount, and ``watch_theme`` re-resolves + rebuilds when the theme changes -
    so bracketed title segments always use the active theme's accent (the
    footer key colour).
    """

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL
        return app

    def test_mount_publishes_theme_accent(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # The published highlight matches the live theme's accent.
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == app.current_theme.accent

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_theme_change_updates_the_accent(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                first = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
                # Switch to a theme with a different accent and confirm the
                # published highlight follows it.
                app.theme = "gruvbox"
                await pilot.pause()
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == app.current_theme.accent
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE != first

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_resolve_accent_is_overridable(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)
        # A child app can retarget the shared accent source without touching
        # the publish plumbing (decision/mechanism split); both per-surface
        # hooks default to resolve_accent, so overriding it feeds both.
        app.resolve_accent = lambda: "#123456"  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == "#123456"

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_mount_publishes_theme_accent_to_selected_frame(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView

        prev = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # The selected-frame accent tracks the live theme's accent -
                # the same resolution path as the title bracket highlight.
                assert KanbanView.SELECTED_FRAME_ACCENT == app.current_theme.accent

        try:
            _run(body())
        finally:
            KanbanView.SELECTED_FRAME_ACCENT = prev

    def test_theme_change_updates_the_selected_frame_accent(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView

        prev = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                first = KanbanView.SELECTED_FRAME_ACCENT
                # Switching themes republishes the new accent onto the frame.
                app.theme = "gruvbox"
                await pilot.pause()
                assert KanbanView.SELECTED_FRAME_ACCENT == app.current_theme.accent
                assert KanbanView.SELECTED_FRAME_ACCENT != first

        try:
            _run(body())
        finally:
            KanbanView.SELECTED_FRAME_ACCENT = prev

    def test_resolve_accent_feeds_both_highlights(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev_bracket = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)
        # The shared default decision hook feeds *both* accent highlights when
        # neither per-surface hook is overridden.
        app.resolve_accent = lambda: "#abcdef"  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == "#abcdef"
                assert KanbanView.SELECTED_FRAME_ACCENT == "#abcdef"

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev_bracket
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_per_surface_hook_varies_frame_from_bracket(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev_bracket = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)
        # A child app can override just one per-surface hook to vary the
        # source per surface; the un-overridden hook still follows the shared
        # resolve_accent default, so the two highlights publish *different*
        # accents.
        app.resolve_accent = lambda: "#111111"  # type: ignore[method-assign]
        app.resolve_frame_accent = lambda: "#222222"  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # The bracket highlight falls through to the shared default ...
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == "#111111"
                # ... while the frame uses its own overridden source.
                assert KanbanView.SELECTED_FRAME_ACCENT == "#222222"
                assert KanbanView.SELECTED_FRAME_ACCENT != TitleHighlight.BRACKET_HIGHLIGHT_STYLE

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev_bracket
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_live_empty_accent_falls_back_to_reverse_frame(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev_bracket = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)
        # A child app resolving an empty accent disables the frame accent, so
        # the selected frame falls back to the theme-safe reverse highlight -
        # end-to-end through the live publish path.
        app.resolve_accent = lambda: ""  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert KanbanView.SELECTED_FRAME_ACCENT == ""
                assert KanbanView.frame_style(True) == "bold reverse"

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev_bracket
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame

    def test_attribute_error_guard_disables_both_highlights(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight

        prev_bracket = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        prev_frame = KanbanView.SELECTED_FRAME_ACCENT
        app = self._app(ctx)

        # A hook that raises AttributeError (e.g. a pre-init theme object with
        # no ``accent``) must degrade both highlights to "" rather than
        # crashing the render.
        def _raise() -> str:
            raise AttributeError("no accent")

        app.resolve_accent = _raise  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert TitleHighlight.BRACKET_HIGHLIGHT_STYLE == ""
                assert KanbanView.SELECTED_FRAME_ACCENT == ""

        try:
            _run(body())
        finally:
            TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev_bracket
            KanbanView.SELECTED_FRAME_ACCENT = prev_frame


class TestRunTui:
    """Tests for the ``run_tui`` entry point dispatch."""

    def test_run_tui_raises_without_textual(self, ctx, monkeypatch):
        import doxtr_doto.cli.tui as tui_pkg

        monkeypatch.setattr(tui_pkg, "TEXTUAL_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="textual"):
            tui_pkg.run_tui(ctx)

    def test_run_tui_constructs_and_runs_app(self, ctx, monkeypatch):
        import doxtr_doto.cli.tui as tui_pkg
        from doxtr_doto.cli.tui.app import DotoApp

        ran = {}

        def fake_run(self):
            ran["app"] = self

        monkeypatch.setattr(DotoApp, "run", fake_run)
        tui_pkg.run_tui(ctx)
        assert isinstance(ran["app"], DotoApp)
        assert ran["app"].ctx is ctx

    def test_run_tui_reconfigures_streams_to_utf8(self, ctx, monkeypatch):
        """``run_tui`` forces stdin/stdout/stderr to UTF-8 before launching.

        Guards user bug #3 (umlauts garbled on a non-UTF-8 locale): the TUI
        must not depend on the user's ``LANG`` to render äöü / box-drawing /
        emoji glyphs.
        """
        import io

        import doxtr_doto.cli.tui as tui_pkg
        from doxtr_doto.cli.tui.app import DotoApp

        monkeypatch.setattr(DotoApp, "run", lambda self: None)

        calls = []

        class _Reconfigurable(io.StringIO):
            def reconfigure(self, *, encoding=None, **kwargs):
                calls.append(encoding)

        monkeypatch.setattr("sys.stdin", _Reconfigurable())
        monkeypatch.setattr("sys.stdout", _Reconfigurable())
        monkeypatch.setattr("sys.stderr", _Reconfigurable())

        tui_pkg.run_tui(ctx)

        # All three standard streams were reconfigured to UTF-8.
        assert calls == ["utf-8", "utf-8", "utf-8"]

    def test_ensure_utf8_io_tolerates_non_reconfigurable_streams(self, monkeypatch):
        """The UTF-8 setup never raises when a stream can't be reconfigured.

        Under pytest capture (or a redirected pipe) a stream may lack
        ``.reconfigure`` or refuse it; the helper must be a no-op rather than
        crashing the TUI launch.
        """
        import io

        import doxtr_doto.cli.tui as tui_pkg

        # A stream with no ``.reconfigure`` at all (e.g. a plain object).
        monkeypatch.setattr("sys.stdin", object())

        # A stream whose ``.reconfigure`` raises (e.g. detached buffer).
        class _Raising(io.StringIO):
            def reconfigure(self, *, encoding=None, **kwargs):
                raise ValueError("underlying buffer detached")

        monkeypatch.setattr("sys.stdout", _Raising())
        monkeypatch.setattr("sys.stderr", _Raising())

        # Must not raise.
        tui_pkg._ensure_utf8_io()


# ---------------------------------------------------------------------------
# Daily kickstart nudge (requirement 5)
# ---------------------------------------------------------------------------
class TestNudgeDecision:
    """Unit tests for the once-per-day nudge decision logic (no rendering)."""

    def test_should_show_when_not_prompted_and_no_focus(self):
        from doxtr_doto.cli.tui import nudge

        assert nudge.should_show_nudge(None, False, "2024-01-02") is True

    def test_suppressed_when_already_prompted_today(self):
        from doxtr_doto.cli.tui import nudge

        assert nudge.should_show_nudge("2024-01-02", False, "2024-01-02") is False

    def test_fires_on_a_new_day(self):
        from doxtr_doto.cli.tui import nudge

        # Prompted yesterday -> fires today (date boundary).
        assert nudge.should_show_nudge("2024-01-01", False, "2024-01-02") is True

    def test_suppressed_when_focus_active(self):
        from doxtr_doto.cli.tui import nudge

        # Even on a fresh day, an active focus timer suppresses the nudge.
        assert nudge.should_show_nudge(None, True, "2024-01-02") is False
        assert nudge.should_show_nudge("2024-01-01", True, "2024-01-02") is False

    def test_today_iso_shape(self):
        from doxtr_doto.cli.tui import nudge

        stamp = nudge.today_iso()
        assert len(stamp) == 10 and stamp.count("-") == 2

    def test_has_active_focus_false_without_session(self, ctx):
        from doxtr_doto.cli.tui import nudge

        assert nudge.has_active_focus(ctx) is False

    def test_has_active_focus_true_when_running(self, ctx, store_file):
        from doxtr_doto.cli.tui import actions, nudge

        actions.toggle_timer(ctx, "T-001")
        assert nudge.has_active_focus(ctx) is True
        actions.toggle_timer(ctx, "T-001")  # stop
        assert nudge.has_active_focus(ctx) is False

    def test_mark_prompted_writes_date(self, ctx):
        from doxtr_doto.cli.tui import nudge

        assert ctx.global_store.load().last_prompt_date is None
        nudge.mark_prompted(ctx, "2024-03-04")
        assert ctx.global_store.load().last_prompt_date == "2024-03-04"

    def test_mark_prompted_defaults_to_today(self, ctx):
        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx)
        assert ctx.global_store.load().last_prompt_date == nudge.today_iso()

    def test_gather_candidates_ranks_and_limits(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import nudge

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        candidates = nudge.gather_candidates(ctx, limit=2)
        assert len(candidates) <= 2
        assert candidates  # at least one ready task
        # Keys are the 1-based shortcut digits in order.
        assert [c.key for c in candidates] == [str(i) for i in range(1, len(candidates) + 1)]
        # High-priority task ranks above the low-priority one.
        titles = [c.title for c in candidates]
        assert "First task" in titles

    def test_gather_candidates_deprioritizes_blocked_same_repo_dep(self, ctx, store_file):
        # Dependency scoring must work under namespacing: a high-priority task
        # blocked by a pending SAME-REPO dependency should be deprioritized
        # below the (lower-priority) task that blocks it.
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import nudge

        data_dict = _load(store_file)
        # T-001 (high) depends on T-002 (low, still open) -> blocked.
        data_dict["tasks"]["T-001"]["depends_on"] = ["T-002"]
        store_file.write_text(json.dumps(data_dict))

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        candidates = nudge.gather_candidates(ctx, limit=2)
        refs = [c.ref for c in candidates]
        # Despite being high priority, the blocked T-001 ranks below its
        # pending dependency T-002. The action ref is the canonical
        # ``repo#id`` form (not the shortened display id), so it always
        # resolves to the owning repo.
        assert refs.index("repoA#T-002") < refs.index("repoA#T-001")


class TestNudgeModal:
    """Pilot-driven tests of the kickstart modal appearing / skipping."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui.app import DotoApp

        return DotoApp(ctx)

    def test_modal_appears_on_launch_when_due(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.screen, KickstartScreen)

        _run(body())

    def test_modal_skip_records_prompt_date(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.screen, KickstartScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, KickstartScreen)

        _run(body())
        assert ctx.global_store.load().last_prompt_date == nudge.today_iso()

    def test_modal_not_shown_when_prompted_today(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        nudge.mark_prompted(ctx, nudge.today_iso())
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert not isinstance(app.screen, KickstartScreen)

        _run(body())

    def test_modal_not_shown_when_focus_active(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import actions
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        actions.toggle_timer(ctx, "T-001")  # active focus timer
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert not isinstance(app.screen, KickstartScreen)

        _run(body())

    def test_modal_candidate_starts_timer(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.screen, KickstartScreen)
                await pilot.press("1")  # start the top candidate
                await pilot.pause()
                assert not isinstance(app.screen, KickstartScreen)

        _run(body())
        # The top candidate (high-priority T-001) now has an open worklog.
        logs = _load(store_file)["tasks"]["T-001"]["worklogs"]
        assert logs and logs[-1]["stopped_at"] is None

    def test_modal_work_clocks_in(self, ctx, store_file, env):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.app import KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.screen, KickstartScreen)
                await pilot.press("w")  # clock in to general work
                await pilot.pause()
                assert not isinstance(app.screen, KickstartScreen)

        _run(body())
        state = ctx.global_store.load()
        assert state.work_clock.worklogs
        assert state.work_clock.worklogs[-1]["stopped_at"] is None

    def test_modal_slash_opens_filter_and_records_prompt(self, ctx, store_file):
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import FilterScreen, KickstartScreen

        RepoRegistry(ctx.global_store).rescan(store_file.parent.parent.parent)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.screen, KickstartScreen)
                await pilot.press("slash")  # open search from the nudge
                await pilot.pause()
                # The kickstart modal gave way to the filter/search modal.
                assert not isinstance(app.screen, KickstartScreen)
                assert isinstance(app.screen, FilterScreen)

        _run(body())
        # The nudge still records today so it fires at most once per day.
        assert ctx.global_store.load().last_prompt_date == nudge.today_iso()


class TestLayoutActions:
    """Unit tests for the TUI-layout persistence actions (no rendering)."""

    def test_default_layout_is_table_when_unset(self, ctx):
        from doxtr_doto.enums import TuiLayout

        # Fresh global state has no tui_layout; must default to table.
        assert actions.load_tui_layout(ctx) == TuiLayout.TABLE

    def test_save_then_load_round_trip(self, ctx):
        from doxtr_doto.enums import TuiLayout

        actions.save_tui_layout(ctx, TuiLayout.KANBAN)
        assert actions.load_tui_layout(ctx) == TuiLayout.KANBAN
        # Persisted to global state as the string value.
        assert ctx.global_store.load().tui_layout == "kanban"

    def test_load_ignores_unknown_value(self, ctx):
        from doxtr_doto.enums import TuiLayout

        state = ctx.global_store.load()
        state.tui_layout = "bogus"
        ctx.global_store.save(state)
        # Unrecognized values fall back to the default table view.
        assert actions.load_tui_layout(ctx) == TuiLayout.TABLE


class TestViewPrefsActions:
    """Unit tests for the TUI filter/sort persistence actions (Feature C)."""

    def test_default_prefs_when_unset(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # Fresh global state has no tui_* filter/sort fields; the recent-done
        # filter is ON by default seeded from the config's
        # tui_recent_done_days (default 10), and every other field defaults.
        assert actions.load_view_prefs(ctx) == ViewPrefs(recent_done_days=10)

    def test_default_prefs_seeds_recent_done_from_nondefault_config(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # With fresh/empty global state, the recent-done window is seeded from
        # the config's tui_recent_done_days - a NON-default value (30) proves
        # the seed is read from config and not hardcoded to 10.
        ctx.config.tui_recent_done_days = 30
        assert actions.load_view_prefs(ctx) == ViewPrefs(recent_done_days=30)

    def test_save_then_load_round_trip(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs
        from doxtr_doto.enums import DueFilter, SortKey, SortOrder

        prefs = ViewPrefs(
            hide_completed=True,
            recent_done_days=10,
            due_filter=DueFilter.WEEK,
            tag_filter="frontend",
            priority_filter="high",
            sort_key=SortKey.PRIORITY,
            sort_order=SortOrder.DESC,
        )
        actions.save_view_prefs(ctx, prefs)
        assert actions.load_view_prefs(ctx) == prefs
        # Persisted to global state as string values (the sort-memory).
        state = ctx.global_store.load()
        assert state.tui_sort_key == "priority"
        assert state.tui_sort_order == "desc"
        assert state.tui_due_filter == "week"

    def test_recent_done_enabled_round_trip(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # An active recent-done window round-trips and persists its on-state
        # and N-day count, overriding the config default on the next load.
        actions.save_view_prefs(ctx, ViewPrefs(recent_done_days=30))
        state = ctx.global_store.load()
        assert state.tui_recent_done_enabled is True
        assert state.tui_recent_done_days == 30
        assert actions.load_view_prefs(ctx).recent_done_days == 30

    def test_recent_done_disabled_persists(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        # Disabling the filter (None) persists as enabled=False so it survives
        # a restart instead of snapping back to the ON-by-default config value.
        actions.save_view_prefs(ctx, ViewPrefs(recent_done_days=None))
        state = ctx.global_store.load()
        assert state.tui_recent_done_enabled is False
        assert actions.load_view_prefs(ctx).recent_done_days is None

    def test_recent_done_invalid_stored_days_falls_back_to_config(self, ctx):
        # A missing stored day count while enabled falls back to the config
        # default (10) rather than breaking the view.
        state = ctx.global_store.load()
        state.tui_recent_done_enabled = True
        state.tui_recent_done_days = None
        ctx.global_store.save(state)
        assert actions.load_view_prefs(ctx).recent_done_days == 10

    def test_recent_done_corrupt_stored_days_falls_back_to_config(self, ctx):
        # A genuinely corrupt (non-numeric) persisted day count must not crash
        # the view: load_view_prefs falls back to the config default (10).
        state = ctx.global_store.load()
        state.tui_recent_done_enabled = True
        state.tui_recent_done_days = "abc"  # type: ignore[assignment]
        ctx.global_store.save(state)
        # Does not raise and falls back to the config default.
        assert actions.load_view_prefs(ctx).recent_done_days == 10

    def test_repo_filter_round_trip(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        prefs = ViewPrefs(repo_filter=("web", "api"))
        actions.save_view_prefs(ctx, prefs)
        # The repo filter round-trips as an (immutable) tuple of names.
        loaded = actions.load_view_prefs(ctx)
        assert loaded.repo_filter == ("web", "api")
        assert loaded == prefs
        # Persisted to global state as a list of names.
        assert ctx.global_store.load().tui_repo_filter == ["web", "api"]

    def test_empty_repo_filter_persists_as_none(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        actions.save_view_prefs(ctx, ViewPrefs(repo_filter=()))
        # An empty repo filter is stored as None (no filter), not an empty list.
        assert ctx.global_store.load().tui_repo_filter is None
        assert actions.load_view_prefs(ctx).repo_filter == ()

    def test_load_ignores_unknown_enum_values(self, ctx):
        from doxtr_doto.cli.tui.filtersort import ViewPrefs
        from doxtr_doto.enums import DueFilter, SortKey, SortOrder

        state = ctx.global_store.load()
        state.tui_due_filter = "bogus"
        state.tui_sort_key = "bogus"
        state.tui_sort_order = "bogus"
        ctx.global_store.save(state)
        prefs = actions.load_view_prefs(ctx)
        # Unrecognized values fall back to each field's default.
        assert prefs.due_filter is DueFilter.ALL
        assert prefs.sort_key is SortKey.NONE
        assert prefs.sort_order is SortOrder.ASC
        # Every other field matches its default; the recent-done filter is ON
        # by default (seeded from the config's tui_recent_done_days, 10).
        assert prefs == ViewPrefs(recent_done_days=10)


class TestDetailRatioActions:
    """Unit tests for the table-layout detail-pane ratio persistence/parse."""

    def test_default_ratio_when_unset(self, ctx):
        from doxtr_doto.cli.tui.actions import DEFAULT_DETAIL_RATIO

        # Fresh global state has no tui_detail_ratio; must default to 3/4.
        assert actions.load_detail_ratio(ctx) == DEFAULT_DETAIL_RATIO == "3/4"

    def test_save_then_load_round_trip(self, ctx):
        actions.save_detail_ratio(ctx, "5/8")
        assert actions.load_detail_ratio(ctx) == "5/8"
        # Persisted to global state verbatim.
        assert ctx.global_store.load().tui_detail_ratio == "5/8"

    def test_save_normalizes_whitespace(self, ctx):
        actions.save_detail_ratio(ctx, " 1 / 2 ")
        assert ctx.global_store.load().tui_detail_ratio == "1/2"
        assert actions.load_detail_ratio(ctx) == "1/2"

    def test_load_falls_back_on_malformed_value(self, ctx):
        state = ctx.global_store.load()
        state.tui_detail_ratio = "garbage"
        ctx.global_store.save(state)
        # A malformed stored value never breaks the layout: default is used.
        assert actions.load_detail_ratio(ctx) == "3/4"

    def test_parse_detail_ratio_semantics(self):
        from doxtr_doto.cli.tui.actions import parse_detail_ratio

        # ``n/d`` -> (top_fr=d-n, detail_fr=n): the detail (bottom) pane takes
        # n/d of the *total* height, the task list (top) the remaining (d-n)/d.
        assert parse_detail_ratio("3/4") == (1, 3)
        assert parse_detail_ratio("5/8") == (3, 5)
        assert parse_detail_ratio("1/2") == (1, 1)
        assert parse_detail_ratio("1/4") == (3, 1)
        # Malformed / zero / out-of-range (n >= d) / missing fall back to the
        # default 3/4 -> (1, 3).
        assert parse_detail_ratio("bad") == (1, 3)
        assert parse_detail_ratio("0/4") == (1, 3)
        assert parse_detail_ratio("4/0") == (1, 3)
        assert parse_detail_ratio("4/4") == (1, 3)
        assert parse_detail_ratio("5/4") == (1, 3)
        assert parse_detail_ratio("") == (1, 3)
        assert parse_detail_ratio(None) == (1, 3)

    def test_normalize_detail_ratio_canonicalizes_and_defaults(self):
        from doxtr_doto.cli.tui.actions import normalize_detail_ratio

        # Well-formed values round-trip to their canonical ``n/d`` form (the
        # numerator is the detail pane's share of the total).
        assert normalize_detail_ratio("3/4") == "3/4"
        assert normalize_detail_ratio("5/8") == "5/8"
        assert normalize_detail_ratio(" 1 / 2 ") == "1/2"
        # Malformed / out-of-range values normalize to the default.
        assert normalize_detail_ratio("bad") == "3/4"
        assert normalize_detail_ratio("4/4") == "3/4"
        assert normalize_detail_ratio("5/4") == "3/4"
        assert normalize_detail_ratio(None) == "3/4"

    def test_global_state_round_trips_detail_ratio(self, ctx):
        # The field survives a to_dict/from_dict round trip (persistence).
        from doxtr_doto.cli.global_state import GlobalState

        state = ctx.global_store.load()
        state.tui_detail_ratio = "5/8"
        restored = GlobalState.from_dict(state.to_dict())
        assert restored.tui_detail_ratio == "5/8"


class TestModalWidthActions:
    """Unit tests for the edit/note pop-up width ratio persistence/parse."""

    def test_default_ratio_when_unset(self, ctx):
        from doxtr_doto.cli.tui.actions import DEFAULT_MODAL_WIDTH_RATIO

        # Fresh global state has no tui_modal_width_ratio; must default to 3/4.
        assert actions.load_modal_width_ratio(ctx) == DEFAULT_MODAL_WIDTH_RATIO == "3/4"

    def test_save_then_load_round_trip(self, ctx):
        actions.save_modal_width_ratio(ctx, "1/2")
        assert actions.load_modal_width_ratio(ctx) == "1/2"
        assert ctx.global_store.load().tui_modal_width_ratio == "1/2"

    def test_save_normalizes_whitespace(self, ctx):
        actions.save_modal_width_ratio(ctx, " 2 / 3 ")
        assert ctx.global_store.load().tui_modal_width_ratio == "2/3"
        assert actions.load_modal_width_ratio(ctx) == "2/3"

    def test_load_falls_back_on_malformed_value(self, ctx):
        state = ctx.global_store.load()
        state.tui_modal_width_ratio = "garbage"
        ctx.global_store.save(state)
        assert actions.load_modal_width_ratio(ctx) == "3/4"

    def test_parse_modal_width_ratio_semantics(self):
        from doxtr_doto.cli.tui.actions import parse_modal_width_ratio

        # ``n/d`` -> (numerator, denominator): the modal takes n/d of the
        # *total* terminal width. Unlike the detail ratio, n == d (full width)
        # is allowed.
        assert parse_modal_width_ratio("3/4") == (3, 4)
        assert parse_modal_width_ratio("1/2") == (1, 2)
        assert parse_modal_width_ratio("1/1") == (1, 1)
        assert parse_modal_width_ratio("4/4") == (4, 4)
        # Malformed / zero / out-of-range (n > d) / missing fall back to 3/4.
        assert parse_modal_width_ratio("bad") == (3, 4)
        assert parse_modal_width_ratio("0/4") == (3, 4)
        assert parse_modal_width_ratio("4/0") == (3, 4)
        assert parse_modal_width_ratio("5/4") == (3, 4)
        assert parse_modal_width_ratio("") == (3, 4)
        assert parse_modal_width_ratio(None) == (3, 4)

    def test_modal_width_percent(self):
        from doxtr_doto.cli.tui.actions import modal_width_percent

        assert modal_width_percent("3/4") == 75
        assert modal_width_percent("1/2") == 50
        assert modal_width_percent("1/1") == 100
        assert modal_width_percent("2/3") == 67  # rounded
        # Malformed falls back to the default 3/4 -> 75%.
        assert modal_width_percent("bad") == 75
        assert modal_width_percent(None) == 75

    def test_normalize_modal_width_ratio_canonicalizes_and_defaults(self):
        from doxtr_doto.cli.tui.actions import normalize_modal_width_ratio

        assert normalize_modal_width_ratio("3/4") == "3/4"
        assert normalize_modal_width_ratio("1/2") == "1/2"
        assert normalize_modal_width_ratio("1/1") == "1/1"
        assert normalize_modal_width_ratio(" 2 / 3 ") == "2/3"
        assert normalize_modal_width_ratio("bad") == "3/4"
        assert normalize_modal_width_ratio("5/4") == "3/4"
        assert normalize_modal_width_ratio(None) == "3/4"

    def test_global_state_round_trips_modal_width_ratio(self, ctx):
        from doxtr_doto.cli.global_state import GlobalState

        state = ctx.global_store.load()
        state.tui_modal_width_ratio = "1/2"
        restored = GlobalState.from_dict(state.to_dict())
        assert restored.tui_modal_width_ratio == "1/2"


class TestDetailRatioApply:
    """The detail ratio is applied to the live table-layout pane heights."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        # Suppress the once-per-day kickstart nudge so the main screen renders
        # directly (so ``F`` opens the view-prefs pop-up, not the kickstart).
        nudge.mark_prompted(ctx, nudge.today_iso())
        return DotoApp(ctx)

    def test_mount_applies_persisted_ratio_to_pane_heights(self, ctx):
        from textual.css.scalar import Unit

        actions.save_detail_ratio(ctx, "5/8")
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                task_list = app.query_one("#task-list")
                task_details = app.query_one("#task-details")
                # 5/8 -> detail pane takes 5/8 of total: task list 3fr,
                # detail pane 5fr.
                assert task_list.styles.height.value == 3.0
                assert task_list.styles.height.unit is Unit.FRACTION
                assert task_details.styles.height.value == 5.0
                assert task_details.styles.height.unit is Unit.FRACTION

        _run(body())

    def test_mount_default_ratio_applies_three_quarters_to_detail(self, ctx):
        from textual.css.scalar import Unit

        # Fresh app, no saved ratio: the default 3/4 must apply at mount so the
        # detail (bottom) pane takes 3/4 of the height (3fr) and the task list
        # the remaining 1/4 (1fr). Guards the default path end-to-end and that
        # the runtime default agrees with the static-CSS placeholder.
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                task_list = app.query_one("#task-list")
                task_details = app.query_one("#task-details")
                assert task_list.styles.height.value == 1.0
                assert task_list.styles.height.unit is Unit.FRACTION
                assert task_details.styles.height.value == 3.0
                assert task_details.styles.height.unit is Unit.FRACTION

        _run(body())

    def test_config_popup_applies_and_persists_ratio(self, ctx):
        from doxtr_doto.cli.tui.app import DetailRatioScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # ``c`` opens the Config domain, ``d`` the detail-size pop-up.
                await pilot.press("c")
                await pilot.press("d")
                await pilot.pause()
                assert isinstance(app.screen, DetailRatioScreen)
                # Simulate applying a 1/2 ratio from the pop-up.
                app.screen.dismiss("1/2")
                await pilot.pause()
                # Applied immediately to the live pane heights: 1/2 -> an even
                # 1fr / 1fr split (detail pane half the total height).
                assert app.query_one("#task-list").styles.height.value == 1.0
                assert app.query_one("#task-details").styles.height.value == 1.0
                # ... stored on the app, and persisted for the next launch.
                assert app.detail_ratio == "1/2"
                assert ctx.global_store.load().tui_detail_ratio == "1/2"

        _run(body())

    def test_config_popup_prepopulates_current_ratio(self, ctx):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import DetailRatioScreen

        actions.save_detail_ratio(ctx, "5/8")
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("c")
                await pilot.press("d")
                await pilot.pause()
                assert isinstance(app.screen, DetailRatioScreen)
                # The ratio input is pre-populated with the persisted value.
                ratio_input = app.screen.query_one("#detailratio-input", Input)
                assert ratio_input.value == "5/8"

        _run(body())

    def test_config_popup_collect_ratio_normalizes_input(self, ctx):
        from doxtr_doto.cli.tui.app import DetailRatioScreen

        app = self._app(ctx)

        async def body():
            from textual.widgets import Input

            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("c")
                await pilot.press("d")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, DetailRatioScreen)
                # A messy entry is canonicalized; a bad one falls back to 3/4.
                screen.query_one("#detailratio-input", Input).value = " 5 / 8 "
                assert screen.collect_ratio() == "5/8"
                screen.query_one("#detailratio-input", Input).value = "nonsense"
                assert screen.collect_ratio() == "3/4"

        _run(body())


def _running_task(tid, **kw):
    """Return a task dict flagged as the active (time-recorded) task."""
    task = {
        "id": tid,
        "title": tid,
        "status": "open",
        "priority": "medium",
        "tags": [],
        "_running": True,
    }
    task.update(kw)
    return task


def _plain_task(tid, **kw):
    """Return an ordinary (not running) task dict."""
    task = {
        "id": tid,
        "title": tid,
        "status": "open",
        "priority": "medium",
        "tags": [],
    }
    task.update(kw)
    return task


class TestActivePinInViews:
    """Feature A: the active (running) task is first in each view's rows."""

    def test_list_view_pins_running_task_first(self):
        from doxtr_doto.cli.tui.filtersort import pin_active_first
        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [_plain_task("A"), _running_task("B"), _plain_task("C")]
        view = ListView()
        # The view consumes an already-active-pinned list (the app's
        # _visible_tasks pins via pin_active_first before passing it in); the
        # view does not re-pin, so it preserves the running-first order.
        view.rebuild(pin_active_first(tasks))
        assert view.row_ids == ["B", "A", "C"]

    def test_kanban_pins_running_task_top_of_its_column(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        tasks = [
            _plain_task("A", status="open"),
            _running_task("B", status="open"),
            _plain_task("C", status="open"),
            _plain_task("D", status="in-progress"),
        ]
        columns = KanbanView.bucket_by_status(tasks, ["open", "in-progress"])
        by_name = dict(columns)
        # In the Open lane the running task is pinned to the top; stable rest.
        assert [t["id"] for t in by_name["open"]] == ["B", "A", "C"]
        assert [t["id"] for t in by_name["in-progress"]] == ["D"]

    def test_calendar_pins_running_task_top_of_its_day(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        tasks = [
            _plain_task("A", due="2024-06-10"),
            _running_task("B", due="2024-06-10"),
            _plain_task("C", due="2024-06-10"),
            _running_task("N", due=None),
            _plain_task("M", due=None),
        ]
        buckets = CalendarView.bucket_by_due(tasks)
        assert [t["id"] for t in buckets["2024-06-10"]] == ["B", "A", "C"]
        # The no-due bucket also pins its running task to the top.
        assert [t["id"] for t in buckets[CalendarView.NO_DUE_KEY]] == ["N", "M"]


class TestVisibleTasksComposition:
    """Feature A + C: ``_visible_tasks`` composes filter + sort + active-pin."""

    def _store_with(self, tmp_path, tasks):
        """Write a JSON store with the given task dicts and return its path."""
        store_path = tmp_path / "compose" / ".doto" / "tasks.json"
        store_path.parent.mkdir(parents=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": dict(tasks),
                    "series": {},
                }
            )
        )
        return store_path

    def _ctx(self, store_path):
        return DotoContext(
            config=load_config(json_path=store_path),
            store=JsonTaskStore(load_config(json_path=store_path).get_json_path()),
            formatter=get_formatter(load_config(json_path=store_path)),
            global_store=GlobalStateStore(),
        )

    def test_composes_text_filter_then_prefs_then_active_pin(self, tmp_path, env):
        from doxtr_doto.cli.tui.app import DotoApp
        from doxtr_doto.cli.tui.filtersort import ViewPrefs
        from doxtr_doto.enums import SortKey, SortOrder

        # One running task (open worklog) that is lowest priority so only the
        # active pin (not the sort) could put it first.
        store_path = self._store_with(
            tmp_path,
            {
                "T-900": {
                    "title": "keep running",
                    "status": "open",
                    "priority": "low",
                    "tags": [],
                    "worklogs": [{"started_at": "2024-01-01T09:00:00+00:00", "stopped_at": None}],
                },
                "T-901": {
                    "title": "keep crit",
                    "status": "open",
                    "priority": "critical",
                    "tags": [],
                    "worklogs": [],
                },
                "T-902": {
                    "title": "drop done",
                    "status": "done",
                    "priority": "high",
                    "tags": [],
                    "worklogs": [],
                },
                "T-903": {
                    "title": "no match",
                    "status": "open",
                    "priority": "high",
                    "tags": [],
                    "worklogs": [],
                },
            },
        )
        ctx = self._ctx(store_path)
        app = DotoApp(ctx)
        # current-repo composition; GLOBAL default would show nothing
        app.scope = DisplayScope.LOCAL
        # Text filter keeps only "keep *" titles; hide completed drops T-902;
        # sort by priority descending would put T-901 (critical) first, but
        # the running T-900 is pinned to the very top (Feature A beats C).
        app.filter_term = "keep"
        app.view_prefs = ViewPrefs(
            hide_completed=True,
            sort_key=SortKey.PRIORITY,
            sort_order=SortOrder.DESC,
        )
        result = app._visible_tasks()
        ids = [t["id"] for t in result]
        assert ids == ["T-900", "T-901"]
        assert result[0]["_running"] is True

    def test_overriding_pin_seam_changes_pipeline(self, tmp_path, env):
        # Feature A/C modularity: a child theme swaps a single pipeline step by
        # setting one DotoApp class attribute (mirroring the ``*_class`` seam).
        # Overriding ``pin_active_first`` with a no-op must stop the running
        # task being pinned, so the configured sort order wins instead.
        from doxtr_doto.cli.tui.app import DotoApp
        from doxtr_doto.cli.tui.filtersort import ViewPrefs
        from doxtr_doto.enums import SortKey, SortOrder

        store_path = self._store_with(
            tmp_path,
            {
                "T-900": {
                    "title": "running low",
                    "status": "open",
                    "priority": "low",
                    "tags": [],
                    "worklogs": [{"started_at": "2024-01-01T09:00:00+00:00", "stopped_at": None}],
                },
                "T-901": {
                    "title": "idle crit",
                    "status": "open",
                    "priority": "critical",
                    "tags": [],
                    "worklogs": [],
                },
            },
        )
        ctx = self._ctx(store_path)

        class _NoPinApp(DotoApp):
            # Swap exactly one pipeline step: a no-op pin that leaves order
            # untouched (returns the list unchanged).
            pin_active_first = staticmethod(lambda tasks: list(tasks))

        app = _NoPinApp(ctx)
        # current-repo composition; GLOBAL default would show nothing
        app.scope = DisplayScope.LOCAL
        app.view_prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.DESC)
        result = app._visible_tasks()
        ids = [t["id"] for t in result]
        # With the no-op pin, priority-desc sort wins: critical before low,
        # i.e. the running low-priority task is NOT pinned to the top.
        assert ids == ["T-901", "T-900"]

        # The default app still pins the running task first (seam untouched).
        default_app = DotoApp(ctx)
        default_app.scope = DisplayScope.LOCAL  # current-repo composition
        default_app.view_prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.DESC)
        default_ids = [t["id"] for t in default_app._visible_tasks()]
        assert default_ids == ["T-900", "T-901"]

    def test_local_scope_ignores_persisted_repo_filter(self, tmp_path, env):
        # P1 regression: a repo filter selected while in GLOBAL (naming a
        # *different* repo) must NOT empty the LOCAL view. LOCAL always shows
        # the current repo and ignores ``repo_filter`` (the scope gate in
        # ``_visible_tasks`` / ``_scoped_view_prefs``).
        from doxtr_doto.cli.tui.app import DotoApp
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        store_path = self._store_with(
            tmp_path,
            {
                "T-900": {
                    "title": "current repo task",
                    "status": "open",
                    "priority": "medium",
                    "tags": [],
                    "worklogs": [],
                },
            },
        )
        ctx = self._ctx(store_path)
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL
        # A persisted repo filter naming a repo that is NOT the current repo.
        app.view_prefs = ViewPrefs(repo_filter=("some-other-repo",))
        result = app._visible_tasks()
        ids = [t["id"] for t in result]
        # The current repo's task is still shown; the filter is ignored.
        assert ids == ["T-900"]
        # The persisted selection is left intact for when the user switches
        # back to GLOBAL (the gate returns a scoped copy, not a mutation).
        assert app.view_prefs.repo_filter == ("some-other-repo",)


class TestListView:
    """Pure-logic tests for the single-column list view classmethods."""

    def test_empty_renders_placeholder(self):
        from doxtr_doto.cli.tui.widgets import ListView

        assert "No tasks" in ListView.format_lines([], 0)

    def test_populated_marks_cursor_row(self):
        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [
            {"id": "T-001", "title": "First", "status": "open", "priority": "high"},
            {"id": "T-002", "title": "Second", "status": "done", "priority": "low"},
        ]
        rendered = ListView.format_lines(tasks, 1)
        assert "T-001" in rendered
        assert "T-002" in rendered
        # The cursor row (index 1) is reverse-highlighted.
        lines = rendered.split("\n")
        assert lines[1].startswith("[reverse]")
        assert not lines[0].startswith("[reverse]")

    def test_done_task_shows_checkbox(self):
        from doxtr_doto.cli.tui.widgets import ListView

        line = ListView.format_line({"id": "T-1", "title": "x", "status": "done"}, False)
        assert "\u2713" in line  # done checkmark

    def test_cursor_line_is_index_when_rows_do_not_wrap(self):
        from doxtr_doto.cli.tui.widgets import ListView

        # Short titles never wrap, so each row is exactly one display line and
        # the cursor's display line equals its index.
        tasks = [
            {"id": f"T-{i}", "title": "short", "status": "open", "priority": "low"}
            for i in range(5)
        ]
        view = ListView()
        view.rebuild(tasks)
        view.cursor = 3
        assert view.cursor_line() == 3

    def test_cursor_line_sums_wrapped_heights_of_rows_above(self):
        from doxtr_doto.cli.tui.widgets import ListView

        # Regression: a row whose title is long enough to wrap occupies several
        # display lines, so the cursor's true display line is the sum of the
        # wrapped heights of the rows above it - not its index. Returning the
        # index let the highlighted row scroll out of the view pane. Build a
        # list of wrapping rows and check the multi-line math is exercised.
        long_title = "x" * 400  # unbroken token forces wrapping at any width
        tasks = [
            {"id": f"T-{i}", "title": long_title, "status": "open", "priority": "low"}
            for i in range(5)
        ]
        view = ListView()
        view.rebuild(tasks)
        width = view._content_width()
        view.cursor = 4  # the fifth row is under the cursor
        expected = sum(view.row_height(view._row_markup[i], width) for i in range(4))
        assert view.cursor_line() == expected
        # The rows wrap, so the cursor line is well past a 1-line-per-row count
        # (proving the wrap-aware math is exercised, not the old index path).
        assert view.cursor_line() > 4

    def test_row_height_counts_wrapped_display_lines(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        single = view.row_height("short line", width=80)
        wrapped = view.row_height("x" * 400, width=80)
        assert single == 1
        assert wrapped > 1

    def test_move_cursor_to_edge_jumps_to_last_and_first(self):
        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [
            {"id": f"T-{i}", "title": "short", "status": "open", "priority": "low"}
            for i in range(5)
        ]
        view = ListView()
        view.rebuild(tasks)
        assert view.cursor == 0
        # Shift+Down jumps straight to the last row.
        view.move_cursor_to_edge(True)
        assert view.cursor == len(tasks) - 1
        assert view.selected_id() == "T-4"
        # Shift+Up jumps straight to the first row.
        view.move_cursor_to_edge(False)
        assert view.cursor == 0
        assert view.selected_id() == "T-0"

    def test_move_cursor_to_edge_empty_is_no_op(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        view.rebuild([])
        view.move_cursor_to_edge(True)
        assert view.cursor == 0
        view.move_cursor_to_edge(False)
        assert view.cursor == 0
        assert view.selected_id() is None

    def test_list_view_select_id_moves_cursor(self):
        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [
            {"id": f"T-{i}", "title": "short", "status": "open", "priority": "low"}
            for i in range(5)
        ]
        view = ListView()
        view.rebuild(tasks)
        assert view.cursor == 0
        # Selecting a present id moves the cursor to that row and reports True.
        assert view.select_id("T-3") is True
        assert view.cursor == 3
        assert view.selected_id() == "T-3"
        # A missing id is a no-op that leaves the cursor and returns False.
        assert view.select_id("T-99") is False
        assert view.cursor == 3

    def test_jump_to_top_scrolls_back_after_jump_to_bottom(self):
        """Regression: Shift+Up after Shift+Down must scroll the list up.

        The list view shares the same jump-to-edge scroll path as kanban, so
        it had the same bug: a jump to the top after a jump to the bottom left
        the frame stuck at the bottom. Asserts the real ``scroll_y`` offset
        returns to 0 on a jump to the top.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [{"id": f"T{i:02d}", "title": f"row {i}"} for i in range(40)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield ListView(id="list")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                view = app.query_one("#list", ListView)
                view.rebuild(tasks)
                view.focus()
                await pilot.pause()
                assert view.max_scroll_y > 0

                view.move_cursor_to_edge(True)
                await pilot.pause()
                assert view.cursor == len(tasks) - 1
                assert view.scroll_y > 0

                view.move_cursor_to_edge(False)
                await pilot.pause()
                assert view.cursor == 0
                assert view.scroll_y == 0

        _run(body())

    def test_select_id_repositions_offscreen_row_into_view(self):
        """select_id must reposition a row that is off screen back into view.

        The list view shares the discontinuous-jump seam
        (:meth:`~AltLayoutView.ensure_cursor_visible`): selecting a row by id
        from the bottom of a long list (frame scrolled down) to a row near the
        top must scroll the frame up so the selected row is visible, rather
        than relying on the direction-inferring smart scroll.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import ListView

        tasks = [{"id": f"T-{i:03d}", "status": "open", "title": f"task {i}"} for i in range(60)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield ListView(id="list")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                view = app.query_one("#list", ListView)
                view.rebuild(tasks)
                view.focus()
                await pilot.pause()
                assert view.max_scroll_y > 0

                # Scroll to the bottom first.
                view.move_cursor_to_edge(True)
                await pilot.pause()
                assert view.scroll_y > 0

                # Select the first row by id: it is off screen at the top.
                assert view.select_id("T-000") is True
                await pilot.pause()
                assert view.selected_id() == "T-000"
                top = view.cursor_line()
                bottom = top + view.cursor_span() - 1
                height = view.size.height
                assert view.scroll_y <= top  # row top visible
                assert bottom < view.scroll_y + height  # row bottom visible
                assert view.scroll_y <= view.cursor_line()

        _run(body())


class TestKanbanView:
    """Pure-logic tests for the kanban bucketing / move classmethods."""

    def test_bucket_by_status_groups_into_columns(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        tasks = [
            {"id": "A", "status": "open"},
            {"id": "B", "status": "done"},
            {"id": "C", "status": "open"},
        ]
        columns = KanbanView.bucket_by_status(tasks, ["open", "in-progress", "done"])
        names = [name for name, _ in columns]
        assert names == ["open", "in-progress", "done"]
        counts = {name: [t["id"] for t in items] for name, items in columns}
        assert counts["open"] == ["A", "C"]
        assert counts["in-progress"] == []
        assert counts["done"] == ["B"]

    def test_unknown_status_goes_to_other_column(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        tasks = [{"id": "A", "status": "weird"}]
        columns = KanbanView.bucket_by_status(tasks, ["open", "done"])
        names = [name for name, _ in columns]
        # An unexpected status is bucketed into the trailing (other) column.
        assert names == ["open", "done", KanbanView.OTHER_COLUMN]
        other = dict(columns)[KanbanView.OTHER_COLUMN]
        assert [t["id"] for t in other] == ["A"]

    def test_other_column_omitted_when_empty(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status([{"id": "A", "status": "open"}], ["open", "done"])
        assert KanbanView.OTHER_COLUMN not in [name for name, _ in columns]

    def test_move_target_status_adjacent_column(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild([{"id": "A", "status": "open"}], ["open", "in-progress", "done"])
        # Cursor on A in the 'open' column; moving right targets 'in-progress'.
        assert view.selected_id() == "A"
        assert view.move_target_status(1) == "in-progress"
        # Moving left off the first column is a no-op.
        assert view.move_target_status(-1) is None

    def test_kanban_select_id_places_cursor_across_lanes(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild(
            [
                {"id": "A", "status": "open"},
                {"id": "B", "status": "in-progress"},
            ],
            ["open", "in-progress", "done"],
        )
        # Cursor starts on A in the first (open) lane.
        assert view.selected_id() == "A"
        # Selecting B (in a different lane) moves both col and row to it.
        assert view.select_id("B") is True
        assert view.selected_id() == "B"
        # A missing id is a no-op that leaves the selection and returns False.
        assert view.select_id("Z") is False
        assert view.selected_id() == "B"

    def test_move_target_status_into_other_is_noop(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        # Two configured columns plus an (other) column; a card in 'done'
        # moving right would hit (other), which is not a valid target.
        view.rebuild(
            [{"id": "A", "status": "done"}, {"id": "B", "status": "weird"}],
            ["open", "done"],
        )
        # Place the cursor on the 'done' column card A.
        for col_index, (name, _items) in enumerate(view.columns):
            if name == "done":
                view.col = col_index
                view.row = 0
        assert view.selected_id() == "A"
        assert view.move_target_status(1) is None

    def test_move_column_relocates_selection_without_moving_card(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild(
            [
                {"id": "A", "status": "open"},
                {"id": "B", "status": "in-progress"},
            ],
            ["open", "in-progress", "done"],
        )
        before = [(n, [t["id"] for t in items]) for n, items in view.columns]
        assert view.col == 0
        assert view.selected_id() == "A"
        # Moving the selection right lands on the next lane's card ...
        assert view.move_column(1) is True
        assert view.col == 1
        assert view.selected_id() == "B"
        # ... and does NOT move any card between columns.
        after = [(n, [t["id"] for t in items]) for n, items in view.columns]
        assert after == before
        # Moving left returns to the first lane.
        assert view.move_column(-1) is True
        assert view.col == 0
        assert view.selected_id() == "A"

    def test_move_column_edges_report_false_and_do_not_wrap(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild([{"id": "A", "status": "open"}], ["open", "in-progress"])
        # At the left edge a further left move is a no-op (no wrap).
        assert view.col == 0
        assert view.move_column(-1) is False
        assert view.col == 0
        # Walk to the last column, then a further right move is a no-op.
        assert view.move_column(1) is True
        assert view.col == len(view.columns) - 1
        assert view.move_column(1) is False
        assert view.col == len(view.columns) - 1

    def test_move_column_clamps_row_into_shorter_destination(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild(
            [
                {"id": "A", "status": "open"},
                {"id": "B", "status": "open"},
                {"id": "C", "status": "in-progress"},
            ],
            ["open", "in-progress"],
        )
        # Select the second card in the 'open' lane (row 1) ...
        view.move_cursor(1)
        assert view.col == 0
        assert view.row == 1
        # ... then move to 'in-progress', which has only one card: the row is
        # clamped so the selection lands on a valid card.
        assert view.move_column(1) is True
        assert view.col == 1
        assert view.row == 0
        assert view.selected_id() == "C"

    def test_move_cursor_to_edge_jumps_within_current_lane(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild(
            [
                {"id": "A", "status": "open"},
                {"id": "B", "status": "open"},
                {"id": "C", "status": "open"},
            ],
            ["open", "in-progress"],
        )
        assert view.col == 0
        assert view.row == 0
        # Shift+Down jumps to the last card of the current (open) lane.
        view.move_cursor_to_edge(True)
        assert view.col == 0
        assert view.row == 2
        assert view.selected_id() == "C"
        # Shift+Up jumps to the first card of the current lane.
        view.move_cursor_to_edge(False)
        assert view.col == 0
        assert view.row == 0
        assert view.selected_id() == "A"

    def test_move_cursor_to_edge_is_relative_to_current_lane(self):
        """Core requirement: the jump targets the *now-current* lane.

        After switching lanes with ``move_column`` a Shift+Down jump must land
        on the last card of the new lane, never move a card between lanes, and
        never reach into the old lane.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild(
            [
                {"id": "A", "status": "open"},
                {"id": "B", "status": "open"},
                {"id": "C", "status": "in-progress"},
                {"id": "D", "status": "in-progress"},
                {"id": "E", "status": "in-progress"},
            ],
            ["open", "in-progress"],
        )
        before = [(n, [t["id"] for t in items]) for n, items in view.columns]
        # Jump to the bottom of the 'open' lane (two cards).
        view.move_cursor_to_edge(True)
        assert view.col == 0
        assert view.row == 1
        assert view.selected_id() == "B"
        # Switch to the 'in-progress' lane and jump to its bottom: it must be
        # the last card of THAT lane (E), not the old lane.
        assert view.move_column(1) is True
        assert view.col == 1
        view.move_cursor_to_edge(True)
        assert view.col == 1
        assert view.row == 2
        assert view.selected_id() == "E"
        # And the top of the now-current lane.
        view.move_cursor_to_edge(False)
        assert view.col == 1
        assert view.row == 0
        assert view.selected_id() == "C"
        # No card ever moved between lanes - only the selection cursor did.
        after = [(n, [t["id"] for t in items]) for n, items in view.columns]
        assert after == before

    def test_move_cursor_to_edge_empty_column_is_no_op(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        view = KanbanView()
        view.rebuild([{"id": "A", "status": "open"}], ["open", "in-progress"])
        # Move the selection to the empty 'in-progress' lane.
        assert view.move_column(1) is True
        assert view.col == 1
        assert view._column_len(view.col) == 0
        view.move_cursor_to_edge(True)
        assert view.row == 0
        view.move_cursor_to_edge(False)
        assert view.row == 0
        assert view.selected_id() is None

    def test_jump_to_top_scrolls_back_after_jump_to_bottom(self):
        """Regression: Shift+Up after Shift+Down must scroll the frame up.

        Repro of the reported kanban bug: jumping to the bottom scrolled the
        frame down (correct), but a subsequent jump to the top left the frame
        stuck showing the bottom cards. The cause was
        :meth:`move_cursor_to_edge` re-anchoring the smart-scroll baseline to
        the landing line and then relying on direction inference in
        :meth:`target_scroll_y`; with ``cursor_line == previous_line`` the move
        was read as *downward* and the snap-to-top branch never fired. The fix
        (:meth:`AltLayoutView.scroll_cursor_to_edge`) scrolls straight to the
        known content edge, so this test asserts the actual ``scroll_y`` offset
        resets to 0 on a jump to the top.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Enough cards in one lane that the column is taller than the viewport,
        # so there is something to scroll.
        tasks = [{"id": f"T{i:02d}", "status": "open", "title": f"card {i}"} for i in range(40)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield KanbanView(id="board")

        app = _Harness()

        async def body():
            # A short viewport guarantees the 40-card lane overflows.
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                board = app.query_one("#board", KanbanView)
                board.rebuild(tasks, ["open", "in-progress"])
                board.focus()
                await pilot.pause()
                assert board.max_scroll_y > 0  # the lane overflows the frame

                # Jump to the bottom: the frame scrolls down.
                board.move_cursor_to_edge(True)
                await pilot.pause()
                assert board.row == len(tasks) - 1
                assert board.scroll_y > 0  # frame moved down (correct)

                # Jump back to the top: the frame must scroll back up to 0 - the
                # bug left it stuck at the bottom here.
                board.move_cursor_to_edge(False)
                await pilot.pause()
                assert board.row == 0
                assert board.scroll_y == 0

        _run(body())

    def test_switching_to_short_lane_repositions_viewport_to_top(self):
        """Regression: switching lanes must make the selected card visible.

        The last unchecked feature: the cursor is at the *bottom* of a long
        ``open`` lane (frame scrolled down), then the user switches (``l``) to
        a one-card ``in-progress`` lane whose single card is at the *top*.
        Relying on the direction-inferring smart scroll
        (:meth:`~AltLayoutView.scroll_to_cursor`) inferred a stale *downward*
        direction and did not reposition, leaving the selected card off
        screen. The discontinuous-jump seam
        (:meth:`~AltLayoutView.ensure_cursor_visible`, wired into
        :meth:`KanbanView.move_column`) repositions the frame so the whole
        selected card is visible: here it scrolls back to the top (``0``).
        Asserts the real ``scroll_y`` offset resets so the selected card's
        span lies within ``[scroll_y .. scroll_y + height)``.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import KanbanView

        # A long 'open' lane (overflows the frame) and a single 'in-progress'
        # card (pinned at the top of its lane).
        tasks = [{"id": f"O{i:02d}", "status": "open", "title": f"open {i}"} for i in range(40)]
        tasks.append({"id": "P00", "status": "in-progress", "title": "only card"})

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield KanbanView(id="board")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                board = app.query_one("#board", KanbanView)
                board.rebuild(tasks, ["open", "in-progress"])
                board.focus()
                await pilot.pause()
                assert board.max_scroll_y > 0  # the open lane overflows

                # Jump to the bottom of the long 'open' lane: frame scrolls
                # down.
                board.move_cursor_to_edge(True)
                await pilot.pause()
                assert board.col == 0
                assert board.row == len(tasks) - 2  # last open card
                assert board.scroll_y > 0  # frame is scrolled down

                # Switch to the one-card 'in-progress' lane, then rebuild the
                # board as the app does after a lane switch
                # (``_kanban_navigate`` -> ``move_column`` -> rebuild). The
                # intervening rebuild re-anchors the smart-scroll baseline
                # (``_sync_scroll_anchor``), so a bare
                # :meth:`~AltLayoutView.scroll_to_cursor` would then read
                # ``cursor_line == previous_line``, infer a stale *downward*
                # move and return None - leaving the card off screen. The
                # discontinuous reposition after the rebuild fixes that.
                assert board.move_column(1) is True
                board.rebuild(tasks, ["open", "in-progress"])
                board.ensure_cursor_visible()
                await pilot.pause()
                assert board.col == 1
                assert board.row == 0
                assert board.selected_id() == "P00"
                # The selected card's full span must now be on screen.
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                height = board.size.height
                assert board.scroll_y <= top  # card top visible
                assert bottom < board.scroll_y + height  # card bottom visible
                # The card sits near the top of its lane, so the frame scrolled
                # back up close to the top (it was deep at the bottom before).
                assert board.scroll_y <= board.cursor_line()

        _run(body())

    def test_select_id_repositions_offscreen_card_into_view(self):
        """select_id must bring a card that is off screen back into view.

        Selecting by id is a *discontinuous* jump, so it goes through the
        direction-free :meth:`~AltLayoutView.ensure_cursor_visible` seam. This
        mimics the app's select-then-rebuild flow
        (:meth:`~doxtr_doto.cli.tui.app.DotoApp.select_task`): after the select
        a rebuild re-anchors the smart-scroll baseline
        (``_sync_scroll_anchor``), so a bare
        :meth:`~AltLayoutView.scroll_to_cursor` reads
        ``cursor_line == previous_line``, takes neither margin branch and
        returns None - leaving the card stuck off screen. The reposition seam
        keeps the selected card visible regardless of the stale baseline.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import KanbanView

        tasks = [{"id": f"T{i:02d}", "status": "open", "title": f"card {i}"} for i in range(40)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield KanbanView(id="board")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                board = app.query_one("#board", KanbanView)
                board.rebuild(tasks, ["open", "in-progress"])
                board.focus()
                await pilot.pause()

                # Scroll to the bottom first.
                board.move_cursor_to_edge(True)
                await pilot.pause()
                assert board.scroll_y > 0

                # Select the first card by id, then rebuild as the app does
                # after a selection - the rebuild re-anchors the baseline so a
                # bare scroll_to_cursor would read cursor == previous and leave
                # the off-screen card unmoved.
                assert board.select_id("T00") is True
                board.rebuild(tasks, ["open", "in-progress"])
                board.ensure_cursor_visible()
                await pilot.pause()
                assert board.selected_id() == "T00"
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                height = board.size.height
                assert board.scroll_y <= top
                assert bottom < board.scroll_y + height
                assert board.scroll_y <= board.cursor_line()

        _run(body())

    def test_ensure_cursor_visible_fixes_stale_direction_none(self):
        """ensure_cursor_visible repositions where scroll_to_cursor returns None.

        The crux of the always-reposition feature: once the smart-scroll
        baseline is re-anchored to the landing line (as every :meth:`rebuild`
        does via ``_sync_scroll_anchor``), :meth:`~AltLayoutView.scroll_to_cursor`
        reads ``cursor_line == previous_line``, infers a (tie-break) *downward*
        move, and - because the card is actually *above* the frame, not within
        the bottom margin - takes neither branch and returns None, leaving the
        selected card off screen. This test drives exactly that state and
        asserts the two seams diverge: the direction-inferring scroll leaves
        the card off screen, while :meth:`~AltLayoutView.ensure_cursor_visible`
        pulls it back into view. It is the regression that fails without the
        new seam.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import KanbanView

        tasks = [{"id": f"T{i:02d}", "status": "open", "title": f"card {i}"} for i in range(40)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield KanbanView(id="board")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                board = app.query_one("#board", KanbanView)
                board.rebuild(tasks, ["open", "in-progress"])
                board.focus()
                await pilot.pause()

                # Deep-scroll to the bottom, then relocate the cursor to the
                # top row and re-anchor the baseline (exactly what a rebuild
                # after a discontinuous selection does).
                board.move_cursor_to_edge(True)
                await pilot.pause()
                deep = board.scroll_y
                assert deep > 0
                board.row = 0
                board._sync_scroll_anchor()

                # scroll_to_cursor sees cursor == previous and returns None:
                # the frame stays deep and the top card is off screen.
                board.scroll_to_cursor()
                await pilot.pause()
                top = board.cursor_line()
                height = board.size.height
                assert not (board.scroll_y <= top < board.scroll_y + height)

                # ensure_cursor_visible makes no direction assumption and pulls
                # the card fully back into view.
                board.ensure_cursor_visible()
                await pilot.pause()
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                assert board.scroll_y <= top
                assert bottom < board.scroll_y + height

        _run(body())

    def test_ensure_cursor_visible_safe_on_empty_destination_lane(self):
        """Switching into an empty lane must reposition safely, not raise.

        ``move_column`` clamps an empty destination to ``row = 0``;
        :meth:`~AltLayoutView.ensure_cursor_visible` then falls back to the
        empty-lane :meth:`cursor_line` (the column header line) and the base
        single-line :meth:`cursor_span`, so from a deep offset it scrolls the
        header line back on screen without raising on the empty column. Guards
        the empty-destination edge (the defensive ``cursor_line`` /
        ``cursor_span`` bounds handling plus the span/offset math).
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import KanbanView

        # A long 'open' lane and a completely empty 'in-progress' lane.
        tasks = [{"id": f"O{i:02d}", "status": "open", "title": f"open {i}"} for i in range(40)]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield KanbanView(id="board")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                board = app.query_one("#board", KanbanView)
                board.rebuild(tasks, ["open", "in-progress"])
                board.focus()
                await pilot.pause()

                # Scroll to the bottom of the long 'open' lane.
                board.move_cursor_to_edge(True)
                await pilot.pause()
                deep = board.scroll_y
                assert deep > 0

                # Switch to the empty 'in-progress' lane: row clamps to 0 and
                # the lane has no card. ensure_cursor_visible must not raise on
                # the empty destination and repositions to show the lane's
                # header line (its content line, which the empty-lane
                # cursor_line falls back to).
                assert board.move_column(1) is True
                assert board.col == 1
                assert board.row == 0
                board.ensure_cursor_visible()
                await pilot.pause()
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                height = board.size.height
                assert board.scroll_y <= top  # header line on screen
                assert bottom < board.scroll_y + height
                assert board.scroll_y < deep  # scrolled back up from the deep offset

        _run(body())

    def test_empty_board_renders_placeholder(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        assert "No statuses" in KanbanView.format_board([], 0, 0)

    def test_format_board_lays_columns_horizontally(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status(
            [
                {"id": "A", "status": "open", "title": "alpha"},
                {"id": "B", "status": "done", "title": "beta"},
            ],
            ["open", "in-progress", "done"],
        )
        board = KanbanView.format_board(columns, 0, 0)
        lines = board.split("\n")
        # The header line carries every column's title side by side (not
        # stacked on separate blocks joined by blank lines).
        header_plain = Text.from_markup(lines[0]).plain
        assert "open" in header_plain
        assert "in-progress" in header_plain
        assert "done" in header_plain
        # The three headers appear in left-to-right order on the one line.
        assert header_plain.index("open") < header_plain.index("in-progress")
        assert header_plain.index("in-progress") < header_plain.index("done")
        # The first card row places the 'open' column's card and the 'done'
        # column's card on the same board line (side by side). Framed cards
        # (Feature 1/2) put the ID line one row below the top border, so scan
        # the board for the first row carrying both ids.
        card_row = next(
            Text.from_markup(line).plain
            for line in lines
            if "A" in Text.from_markup(line).plain and "B" in Text.from_markup(line).plain
        )
        assert "A" in card_row
        assert "B" in card_row
        assert card_row.index("A") < card_row.index("B")

    def test_format_column_returns_header_and_cards(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        lines = KanbanView.format_column(
            "open",
            [{"id": "A", "status": "open", "title": "alpha"}],
            focused=True,
            cursor_row=0,
            width=26,
            show_priority=False,
        )
        # Header line, then one fixed-size framed square card (Feature 1):
        # a top border, ``card_height`` interior+border rows. The whole
        # column is 1 header + card_height lines.
        card_height = KanbanView.card_height(
            {"id": "A", "title": "alpha"}, width=26, show_priority=False
        )
        assert len(lines) == KanbanView.HEADER_LINES + card_height
        assert "open (1)" in lines[0]
        # The ID + due first line sits one row below the top frame border.
        assert "A" in lines[2]
        # The card's title is wrapped onto a body row beneath the ID.
        assert any("alpha" in line for line in lines)
        # The selected card is marked by a highlighted *frame* (Feature 2),
        # not reverse-video over the whole card body: the border rows carry the
        # selected frame style (now ``bold reverse``). Both the header
        # (lines[0], ACTIVE_COLUMN_STYLE) and the selected-card frame cells
        # legitimately carry reverse-video markup; what must stay unmarked is
        # the card *body* text between the frame columns. Strip the known frame
        # markup from the card lines and assert no stray reverse span remains.
        assert KanbanView.SELECTED_FRAME_STYLE in lines[1]
        frame_open = f"[{KanbanView.SELECTED_FRAME_STYLE}]"
        frame_close = f"[/{KanbanView.SELECTED_FRAME_STYLE}]"
        for line in lines[1:]:
            body = line.replace(frame_open, "").replace(frame_close, "")
            assert "[reverse]" not in body

    def test_format_header_colors_focused_column(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # The active (focused) lane's header is wrapped in
        # ACTIVE_COLUMN_STYLE; an unfocused header is not (Feature 2).
        focused = KanbanView.format_header("open", 3, focused=True)
        unfocused = KanbanView.format_header("open", 3, focused=False)
        assert KanbanView.ACTIVE_COLUMN_STYLE in focused
        assert KanbanView.ACTIVE_COLUMN_STYLE not in unfocused
        # Default (no focused arg) matches the unfocused rendering so existing
        # callers and child themes are unchanged.
        assert KanbanView.format_header("open", 3) == unfocused

    def test_format_empty_placeholder_colors_focused_column(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # The focused empty lane's (empty) placeholder is colored with
        # ACTIVE_COLUMN_STYLE; the unfocused one keeps the dim styling.
        focused = KanbanView.format_empty_placeholder(focused=True)
        unfocused = KanbanView.format_empty_placeholder(focused=False)
        assert KanbanView.ACTIVE_COLUMN_STYLE in focused
        assert KanbanView.ACTIVE_COLUMN_STYLE not in unfocused
        # The default (no arg) matches the unfocused rendering.
        assert KanbanView.format_empty_placeholder() == unfocused
        # Both carry the (empty) text (markup stripped).
        assert "(empty)" in Text.from_markup(focused).plain
        assert "(empty)" in Text.from_markup(unfocused).plain

    def test_active_column_coloring_does_not_change_width(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Coloring the active lane must not change the *visible* (computed)
        # column width: a focused header has the same cell_len as an unfocused
        # one (the accent markup occupies no screen columns), so board
        # alignment / pad_cell width is unaffected (Feature 2).
        focused_header = KanbanView.format_header("in-progress", 2, focused=True)
        unfocused_header = KanbanView.format_header("in-progress", 2, focused=False)
        assert (
            Text.from_markup(focused_header).cell_len == Text.from_markup(unfocused_header).cell_len
        )
        # Likewise for the (empty) placeholder.
        focused_empty = KanbanView.format_empty_placeholder(focused=True)
        unfocused_empty = KanbanView.format_empty_placeholder(focused=False)
        assert (
            Text.from_markup(focused_empty).cell_len == Text.from_markup(unfocused_empty).cell_len
        )
        # pad_cell measures visible width, so a focused and unfocused header
        # pad to the identical cell string at the same target width.
        width = max(
            Text.from_markup(focused_header).cell_len,
            Text.from_markup(unfocused_header).cell_len,
        )
        assert (
            Text.from_markup(KanbanView.pad_cell(focused_header, width)).cell_len
            == Text.from_markup(KanbanView.pad_cell(unfocused_header, width)).cell_len
            == width
        )

    def test_format_column_colors_focused_empty_lane(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # A focused *empty* lane colors both its header and its (empty)
        # placeholder, so the active lane is marked even with no card frame.
        focused = KanbanView.format_column(
            "blocked",
            [],
            focused=True,
            cursor_row=0,
            width=20,
            show_priority=False,
        )
        assert KanbanView.ACTIVE_COLUMN_STYLE in focused[0]
        assert any(KanbanView.ACTIVE_COLUMN_STYLE in line for line in focused[1:])
        # The same empty lane unfocused colors neither.
        unfocused = KanbanView.format_column(
            "blocked",
            [],
            focused=False,
            cursor_row=0,
            width=20,
            show_priority=False,
        )
        assert all(KanbanView.ACTIVE_COLUMN_STYLE not in line for line in unfocused)

    def test_pad_cell_truncates_to_visible_width(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        padded = KanbanView.pad_cell("[bold]hi[/bold]", 10)
        # Padding is measured against the *visible* width (markup excluded).
        assert Text.from_markup(padded).cell_len == 10
        # A cell *wider* than the width is truncated so it never spills into
        # the next column (measured by visible width, markup preserved).
        wide = "[bold]" + "x" * 12 + "[/bold]"
        truncated = KanbanView.pad_cell(wide, 10)
        assert Text.from_markup(truncated).cell_len == 10

    def test_card_first_line_shows_id_and_due(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        line = KanbanView.format_card_first_line(
            {"id": "T-1", "due": "2099-01-15"}, show_priority=False
        )
        plain = Text.from_markup(line).plain
        assert "T-1" in plain
        assert "2099-01-15" in plain

    def test_card_first_line_uses_due_placeholder_when_undated(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        line = KanbanView.format_card_first_line({"id": "T-1"}, show_priority=False)
        plain = Text.from_markup(line).plain
        # No due date -> the stable placeholder keeps the min width constant.
        assert KanbanView.DUE_PLACEHOLDER in plain

    def test_min_card_width_fits_id_plus_due(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status(
            [{"id": "VERY-LONG-TASK-ID-123", "status": "open"}],
            ["open"],
        )
        minimum = KanbanView.min_card_width(columns)
        # The minimum width is at least the widest ID + due-placeholder line.
        first = KanbanView.format_card_first_line(
            {"id": "VERY-LONG-TASK-ID-123"}, show_priority=False
        )
        from rich.text import Text

        assert minimum >= Text.from_markup(first).cell_len
        assert minimum >= KanbanView.MIN_COLUMN_WIDTH

    def test_card_wraps_description_below_first_line(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        long_title = "this is a fairly long task description that must wrap"
        card = KanbanView.format_card(
            {"id": "T-1", "title": long_title},
            highlighted=False,
            width=20,
            show_priority=False,
        )
        # First line is ID + due; the description wraps onto >1 body line.
        assert len(card) > 2

    def test_format_card_defaults_width_and_priority(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Omitting width/show_priority derives them so pure callers still get
        # a sensible, deterministic card without a live viewport.
        card = KanbanView.format_card({"id": "T-1", "title": "x"}, highlighted=False)
        assert isinstance(card, list)
        # The first line is the top frame border; the ID appears on an
        # interior row below it (Feature 1 framed square cards).
        assert card
        assert any("T-1" in line for line in card)

    def test_card_height_matches_format_card_line_count(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Fix 5: card_height counts lines without rendering markup, and must
        # equal len(format_card(...)) for the same inputs so cursor_line's
        # arithmetic stays in lockstep with the rendered block.
        for title in ("", "short", "this is a fairly long task description that wraps"):
            task = {"id": "T-1", "title": title}
            height = KanbanView.card_height(task, width=20, show_priority=False)
            lines = KanbanView.format_card(task, False, width=20, show_priority=False)
            assert height == len(lines)
            assert height >= 1  # always at least the first line

    def test_format_card_fallback_priority_matches_show_priority(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Fix 3: format_card's show_priority=None fallback and
        # KanbanView.show_priority must agree on the same priority-fit rule.
        # Build a single-card board and compare the two at the boundary.
        columns = KanbanView.bucket_by_status(
            [{"id": "A", "status": "open", "priority": "high"}], ["open"]
        )
        minimum = KanbanView.min_card_width(columns)
        for width in (
            minimum,
            minimum + KanbanView.PRIORITY_WIDTH - 1,
            minimum + KanbanView.PRIORITY_WIDTH,
        ):
            fallback = KanbanView._priority_fits(width, minimum)
            assert KanbanView.show_priority(columns, width) == fallback

    def test_cursor_line_sums_block_heights_of_cards_above(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Fix 5: cursor_line = HEADER_LINES + sum of the block heights of the
        # cards above the cursor in the focused column, using card_height for
        # the multi-line math. Build a column of wrapping cards and check it.
        long_title = "this is a fairly long task description that will wrap onto several lines"
        tasks = [{"id": f"T-{i}", "status": "open", "title": long_title} for i in range(4)]
        view = KanbanView()
        view.rebuild(tasks, ["open"])
        width = view._column_width
        show_priority = view._show_priority
        view.col = 0
        view.row = 3  # the fourth card is under the cursor
        items = view.columns[0][1]
        expected = KanbanView.HEADER_LINES + sum(
            KanbanView.card_height(items[i], width=width, show_priority=show_priority)
            for i in range(3)
        )
        assert view.cursor_line() == expected
        # The cards wrap, so the cursor line is well past a 1-line-per-card
        # count (proving the multi-line math is exercised).
        assert view.cursor_line() > KanbanView.HEADER_LINES + 3

    def test_cursor_span_returns_card_height(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Scroll fix: cursor_span is the highlighted card's full line span so
        # the shared smart-scroll keeps the whole card on screen. It must
        # equal the rendered card_height using the same cached width/priority.
        tasks = [{"id": f"T-{i}", "status": "open", "title": "x"} for i in range(3)]
        view = KanbanView()
        view.rebuild(tasks, ["open"])
        view.col = 0
        view.row = 1
        items = view.columns[0][1]
        expected = KanbanView.card_height(
            items[1], width=view._column_width, show_priority=view._show_priority
        )
        assert view.cursor_span() == expected
        assert view.cursor_span() > 1  # a card is multi-line

    def test_base_cursor_span_is_one(self):
        from doxtr_doto.cli.tui.widgets import AltLayoutView

        # The base hook returns 1 so the list/calendar single-line behavior is
        # preserved (one content line per cursor item).
        view = AltLayoutView.__new__(AltLayoutView)
        assert view.cursor_span() == 1

    def test_wrap_text_never_exceeds_inner_width(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        wrapped = KanbanView.wrap_text("alpha beta gamma delta epsilon zeta eta theta", 16)
        inner = 16 - 2
        assert wrapped  # produced some lines
        assert all(len(line) <= inner for line in wrapped)

    def test_wrap_text_hard_splits_overlong_word(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        wrapped = KanbanView.wrap_text("x" * 40, 16)
        inner = 16 - 2
        # A single overlong word is hard-split so it never overflows.
        assert len(wrapped) > 1
        assert all(len(line) <= inner for line in wrapped)

    def test_board_cells_never_spill_into_next_column(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status(
            [
                {"id": "A", "status": "open", "title": "a long title that wraps"},
                {"id": "B", "status": "done", "title": "another lengthy card title"},
            ],
            ["open", "done"],
        )
        width = 18
        board = KanbanView.format_board(columns, 0, 0, width=width, show_priority=False)
        gap = len(KanbanView.COLUMN_GAP)
        for row in board.split("\n"):
            # Each (non-last) column cell occupies exactly ``width`` visible
            # columns, so nothing bleeds past its column boundary. The last
            # cell is rstripped, so measure the whole row's visible width is
            # at most two columns + one gap.
            visible = Text.from_markup(row).cell_len
            assert visible <= width * 2 + gap

    def test_priority_shown_only_when_space_allows(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status([{"id": "A", "status": "open"}], ["open"])
        minimum = KanbanView.min_card_width(columns)
        # Exactly at the minimum width: no room for the priority badge.
        assert KanbanView.show_priority(columns, minimum) is False
        # Minimum + the priority budget: the badge is shown.
        assert KanbanView.show_priority(columns, minimum + KanbanView.PRIORITY_WIDTH) is True

    def test_column_width_spaces_columns_evenly(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status(
            [{"id": "A", "status": "open"}, {"id": "B", "status": "done"}],
            ["open", "done"],
        )
        # A wide terminal spaces the two columns evenly (>= the minimum).
        wide = KanbanView.column_width(columns, 100)
        gap = len(KanbanView.COLUMN_GAP)
        assert wide == (100 - gap) // 2
        # A narrow terminal clamps to the per-board minimum.
        narrow = KanbanView.column_width(columns, 4)
        assert narrow == KanbanView.min_card_width(columns)

    # ------------------------------------------------------------------
    # Feature 1 - square (fixed width + height) cards with clipped body.
    # ------------------------------------------------------------------
    def test_card_interior_rows_approximates_a_square(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # A terminal cell is ~2x taller than wide, so a visual square uses
        # about width / CARD_ASPECT rows (clamped to the min/max row bounds).
        width = 20
        rows = KanbanView.card_interior_rows(width)
        expected = int(round(width / KanbanView.CARD_ASPECT))
        expected = max(KanbanView.MIN_CARD_ROWS, min(KanbanView.MAX_CARD_ROWS, expected))
        assert rows == expected
        # The derived row count is clamped between the configured bounds.
        assert KanbanView.card_interior_rows(2) == KanbanView.MIN_CARD_ROWS
        assert KanbanView.card_interior_rows(1000) == KanbanView.MAX_CARD_ROWS

    def test_card_is_fixed_height_regardless_of_body_length(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 24
        short = KanbanView.format_card(
            {"id": "T-1", "title": "short"},
            highlighted=False,
            width=width,
            show_priority=False,
        )
        long = KanbanView.format_card(
            {
                "id": "T-2",
                "title": "this is a very long description " * 10,
            },
            highlighted=False,
            width=width,
            show_priority=False,
        )
        # Both cards are the SAME fixed height - a long body is clipped rather
        # than making the card grow (Feature 1).
        assert len(short) == len(long)
        assert len(short) == KanbanView.card_height({"id": "T-1"}, width=width, show_priority=False)

    def test_card_rows_never_exceed_the_column_width(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 22
        card = KanbanView.format_card(
            {"id": "T-1", "title": "alpha beta gamma delta epsilon zeta eta theta iota"},
            highlighted=False,
            width=width,
            show_priority=False,
        )
        # Every framed row is exactly ``width`` visible columns wide (both
        # frame borders included), so the square card never spills past its
        # column into the neighbor.
        for row in card:
            assert Text.from_markup(row).cell_len == width

    def test_clip_body_marks_overflow_with_ellipsis(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        lines = ["one", "two", "three", "four"]
        clipped = KanbanView.clip_body(lines, 2)
        assert len(clipped) == 2
        # The last kept line carries the clip indicator so the user knows the
        # body continues beyond the fixed square footprint.
        assert clipped[-1].endswith(KanbanView.CLIP_INDICATOR)
        # A body that fits is returned unchanged (no indicator).
        assert KanbanView.clip_body(["a", "b"], 4) == ["a", "b"]
        # A zero/negative row budget yields no body rows.
        assert KanbanView.clip_body(lines, 0) == []
        # The empty-last-line branch: when the kept line is blank, the
        # indicator becomes the sole content of the last row.
        assert KanbanView.clip_body(["a", "", "c"], 2) == ["a", KanbanView.CLIP_INDICATOR]

    def test_clip_body_ellipsis_survives_full_width_line(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        inner = 8
        indicator = KanbanView.CLIP_INDICATOR
        # A kept line that already fills the inner width must be trimmed to
        # leave room for the ellipsis, so it is not truncated back off later
        # by pad_cell on a full-width body row.
        full = "x" * inner
        clipped = KanbanView.clip_body([full, "more"], 1, inner)
        assert clipped[-1].endswith(indicator)
        # And the trimmed line still fits the inner width (ellipsis included).
        assert Text(clipped[-1]).cell_len <= inner

    def test_long_body_full_width_card_keeps_clip_indicator(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # A long run of width-filling words (no trailing slack) must still
        # show the clip indicator through the full format_card -> pad_cell
        # pipeline rather than having the ellipsis silently truncated.
        width = 18
        card = KanbanView.format_card(
            {"id": "T-1", "title": ("wwwwwwwwwwww " * 20)},
            highlighted=False,
            width=width,
            show_priority=False,
        )
        assert any(KanbanView.CLIP_INDICATOR in row for row in card)

    def test_wrap_text_wraps_by_visible_width_for_wide_chars(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 10  # inner = width - frame_overhead() (2) = 8 columns
        inner = width - KanbanView.frame_overhead()
        # Wide (CJK) characters occupy two columns each; wrapping must honor
        # visible width so no wrapped line exceeds the inner column count.
        wrapped = KanbanView.wrap_text("\u4f60\u597d\u4e16\u754c\u4f60\u597d\u4e16\u754c", width)
        assert wrapped
        for line in wrapped:
            assert Text(line).cell_len <= inner

    def test_long_body_card_shows_clip_indicator(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        card = KanbanView.format_card(
            {"id": "T-1", "title": "word " * 60},
            highlighted=False,
            width=18,
            show_priority=False,
        )
        # Somewhere in the rendered rows the clip indicator appears, proving
        # the overflowing body was truncated rather than growing the card.
        assert any(KanbanView.CLIP_INDICATOR in row for row in card)

    def test_card_height_tracks_width_via_aspect(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # The fixed card height is frame top + interior rows + frame bottom,
        # and the interior rows scale with the width (square aspect).
        task = {"id": "T-1", "title": "body"}
        for width in (16, 24, 40):
            height = KanbanView.card_height(task, width=width, show_priority=False)
            assert height == 2 + KanbanView.card_interior_rows(width)
            # format_card emits exactly card_height lines (lockstep invariant).
            assert (
                len(KanbanView.format_card(task, False, width=width, show_priority=False)) == height
            )

    # ------------------------------------------------------------------
    # Feature 2 - selected cards are marked by a highlighted *frame*.
    # ------------------------------------------------------------------
    def test_frame_style_switches_on_selection(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        assert KanbanView.frame_style(True) == KanbanView.SELECTED_FRAME_STYLE
        assert KanbanView.frame_style(False) == KanbanView.FRAME_STYLE

    def test_selected_card_highlights_frame_not_whole_card(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 24
        selected = KanbanView.format_card(
            {"id": "T-1", "title": "body"},
            highlighted=True,
            width=width,
            show_priority=False,
        )
        unselected = KanbanView.format_card(
            {"id": "T-1", "title": "body"},
            highlighted=False,
            width=width,
            show_priority=False,
        )
        # The selected card's frame (top border) carries the selected style ...
        assert KanbanView.SELECTED_FRAME_STYLE in selected[0]
        # ... and the unselected card's frame does not.
        assert KanbanView.SELECTED_FRAME_STYLE not in unselected[0]
        # The highlight marks the *frame* (border + corners), not the whole
        # card body: the selected-frame style now uses reverse-video
        # (``bold reverse``), so ``[reverse]`` legitimately appears inside the
        # frame-cell markup - but the card's *body* text (the content between
        # the two frame columns on each interior row) must not be independently
        # reverse-highlighted. Strip the known frame markup from each row and
        # assert no stray reverse span survives over the body text.
        frame_open = f"[{KanbanView.SELECTED_FRAME_STYLE}]"
        frame_close = f"[/{KanbanView.SELECTED_FRAME_STYLE}]"
        for row in selected:
            body = row.replace(frame_open, "").replace(frame_close, "")
            assert "[reverse]" not in body

    def test_frame_borders_are_box_drawing_chars(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        card = KanbanView.format_card(
            {"id": "T-1", "title": "body"},
            highlighted=False,
            width=20,
            show_priority=False,
        )
        top = Text.from_markup(card[0]).plain
        bottom = Text.from_markup(card[-1]).plain
        tl, tr, bl, br, horiz, vert = KanbanView.FRAME_CHARS
        assert top.startswith(tl) and top.endswith(tr)
        assert bottom.startswith(bl) and bottom.endswith(br)
        assert horiz in top and horiz in bottom
        # Interior rows carry the vertical side borders.
        assert Text.from_markup(card[1]).plain.startswith(vert)
        assert Text.from_markup(card[1]).plain.endswith(vert)

    def test_overridden_frame_seam_reaches_rendered_card(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        class _SentinelFrameKanbanView(KanbanView):
            """A themed kanban view overriding the new frame seams."""

            FRAME_CHARS = ("A", "B", "C", "D", "=", "|")
            SELECTED_FRAME_STYLE = "magenta"

        card = _SentinelFrameKanbanView.format_card(
            {"id": "T-1", "title": "body"},
            highlighted=True,
            width=20,
            show_priority=False,
        )
        top = Text.from_markup(card[0]).plain
        bottom = Text.from_markup(card[-1]).plain
        # The overridden FRAME_CHARS reach the rendered borders ...
        assert top.startswith("A") and top.endswith("B")
        assert bottom.startswith("C") and bottom.endswith("D")
        assert "=" in top
        # ... and the overridden selected-frame style reaches the markup,
        # proving the frame_style seam is honored end-to-end.
        assert "magenta" in card[0]

    # ------------------------------------------------------------------
    # Feature 2b - the selected frame uses the theme accent hex when the live
    # app publishes one (SELECTED_FRAME_ACCENT), falling back to the theme-safe
    # ``bold reverse`` when none is set.
    # ------------------------------------------------------------------
    def test_frame_style_prefers_accent_hex_when_published(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        prev = KanbanView.SELECTED_FRAME_ACCENT
        try:
            KanbanView.SELECTED_FRAME_ACCENT = "#ffa62b"
            # A published accent hex is preferred for the *selected* frame ...
            selected = KanbanView.frame_style(True)
            assert "#ffa62b" in selected
            # ... and the unselected frame is unchanged (plain FRAME_STYLE).
            assert KanbanView.frame_style(False) == KanbanView.FRAME_STYLE
        finally:
            KanbanView.SELECTED_FRAME_ACCENT = prev

    def test_frame_style_falls_back_to_reverse_without_accent(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # The default (no published accent) pins the backward-compatible,
        # theme-safe reverse highlight for selected cards.
        assert KanbanView.SELECTED_FRAME_ACCENT == ""
        assert KanbanView.frame_style(True) == KanbanView.SELECTED_FRAME_STYLE
        assert KanbanView.frame_style(True) == "bold reverse"
        assert KanbanView.frame_style(False) == KanbanView.FRAME_STYLE

    def test_accent_frame_is_width_neutral_and_colours_the_border(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        accent = "#ffa62b"
        prev = KanbanView.SELECTED_FRAME_ACCENT
        width = 24
        try:
            KanbanView.SELECTED_FRAME_ACCENT = accent
            card = KanbanView.format_card(
                {"id": "T-1", "title": "body"},
                highlighted=True,
                width=width,
                show_priority=False,
            )
            # The accent must not change geometry: every row stays exactly the
            # column width in visible columns (markup occupies no columns).
            for row in card:
                assert _visible_width(row) == width
            # The accent hex reaches the top *and* bottom frame border rows.
            assert accent in card[0]
            assert accent in card[-1]
        finally:
            KanbanView.SELECTED_FRAME_ACCENT = prev

    def test_full_board_accent_is_width_stable_and_colours_selected_column(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        accent = "#ffa62b"
        prev = KanbanView.SELECTED_FRAME_ACCENT
        width = 20
        tasks = [
            {"id": "T-1", "status": "open", "title": "alpha"},
            {"id": "T-2", "status": "done", "title": "beta"},
        ]
        columns = KanbanView.bucket_by_status(tasks, ["open", "done"])
        gap = len(KanbanView.COLUMN_GAP)
        board_width = len(columns) * width + (len(columns) - 1) * gap
        try:
            # A no-accent render establishes the baseline per-row widths.
            KanbanView.SELECTED_FRAME_ACCENT = ""
            plain_board = KanbanView.format_board(columns, 0, 0, width=width, show_priority=False)
            plain_widths = [Text.from_markup(line).cell_len for line in plain_board.split("\n")]
            # The published accent must not change geometry: every board row
            # keeps its exact visible width (markup occupies no columns), and
            # no row exceeds the full board width.
            KanbanView.SELECTED_FRAME_ACCENT = accent
            board = KanbanView.format_board(columns, 0, 0, width=width, show_priority=False)
            lines = board.split("\n")
            accent_widths = [Text.from_markup(line).cell_len for line in lines]
            assert accent_widths == plain_widths
            for w in accent_widths:
                assert w <= board_width
            # The accent hex appears in the selected (open) column's framed
            # rows - the full board publishes it, not just a bare card.
            assert any(accent in line for line in lines)
        finally:
            KanbanView.SELECTED_FRAME_ACCENT = prev

    def test_child_theme_accent_override_without_app_publish(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        class _AccentFrameKanbanView(KanbanView):
            """A child theme pinning its own selected-frame accent in one place."""

            SELECTED_FRAME_ACCENT = "#abcdef"

        card = _AccentFrameKanbanView.format_card(
            {"id": "T-1", "title": "body"},
            highlighted=True,
            width=20,
            show_priority=False,
        )
        # The subclass's accent reaches the rendered frame without the app ever
        # publishing - the SELECTED_FRAME_ACCENT seam is honoured per class ...
        assert "#abcdef" in card[0]
        # ... while the base class keeps its own (empty) default untouched.
        assert KanbanView.SELECTED_FRAME_ACCENT == ""
        # The border glyphs still render (the accent only colours them).
        tl, _tr, _bl, _br, _horiz, _vert = KanbanView.FRAME_CHARS
        assert Text.from_markup(card[0]).plain.startswith(tl)

    # ------------------------------------------------------------------
    # Theme-contrast guard: the active-lane / selected-frame highlights must
    # not regress to the old low-contrast ``bold cyan`` that made the active
    # lane name ('Open') invisible on light themes (user bug #2).
    # ------------------------------------------------------------------
    def test_highlight_styles_are_not_low_contrast_cyan(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # The invisible-'Open' bug was a hardcoded ``bold cyan`` highlight,
        # which blends into light/muted backgrounds. The active-lane header
        # and the selected-card frame must never silently revert to it.
        assert KanbanView.ACTIVE_COLUMN_STYLE != "bold cyan"
        assert KanbanView.SELECTED_FRAME_STYLE != "bold cyan"
        # The active lane highlight must be theme-safe: reverse-video
        # (swaps the theme's own fg/bg) - never a bare fixed hue like
        # ``cyan``/``yellow`` that cannot adapt per theme, and never a Textual
        # CSS theme token like ``$accent`` (those resolve only in CSS, not in
        # Rich/Textual console markup, where they crash or are ignored).
        assert "reverse" in KanbanView.ACTIVE_COLUMN_STYLE
        assert "$" not in KanbanView.ACTIVE_COLUMN_STYLE
        # The selected-card frame also uses reverse-video (theme-safe), not a
        # fixed hue and not a CSS theme token.
        assert "reverse" in KanbanView.SELECTED_FRAME_STYLE
        assert "$" not in KanbanView.SELECTED_FRAME_STYLE

    def test_console_markup_never_contains_theme_tokens(self):
        """No TUI console-markup string may embed a Textual CSS theme token.

        Regression guard for the crash introduced by commit dcaed6f: it put
        Textual CSS *design tokens* (``$accent`` / ``$secondary``) inside
        Rich/Textual *console markup* strings. Those tokens resolve only in a
        CSS context, never in ``[...]`` console markup:

        * ``[$accent]x[/$accent]`` raises ``rich.errors.MarkupError`` (the
          closing tag matches no open tag) - this hard-crashed the whole TUI
          on launch because :meth:`RepoTree.format_repo` renders the current
          repo's ``(here)`` marker on essentially every start.
        * ``[bold $accent]x[/bold $accent]`` does not crash but ``$accent`` is
          silently ignored by Rich, so the intended per-theme color is simply
          not applied (a silent no-op).

        This test asserts the markup emitted by every method/attribute that
        regressed parses with :func:`rich.text.Text.from_markup` *without*
        raising, and that none of them contains a ``$`` character - which
        would mean a theme token leaked back into console markup. It directly
        reproduces (and now forbids) the exact crash and silent-no-op.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.theme import styled
        from doxtr_doto.cli.tui.widgets import (
            KanbanView,
            RepoTree,
            TaskDetails,
        )

        def assert_valid_markup(markup: str) -> None:
            assert "$" not in markup, f"theme token leaked into markup: {markup!r}"
            # Raises rich.errors.MarkupError on an invalid/mismatched tag.
            Text.from_markup(markup)

        # 1. The exact hard-crash site: the current-repo ``(here)`` marker.
        assert_valid_markup(RepoTree.format_repo("r", "r"))
        # A non-current repo returns a bare name (still valid, no token).
        assert_valid_markup(RepoTree.format_repo("a", "b"))

        # 2. The open-interval marker in the details pane.
        assert_valid_markup(TaskDetails.format_interval("09:00", "10:00", "1h", is_open=True))
        assert_valid_markup(TaskDetails.format_interval("09:00", "10:00", "1h", is_open=False))

        # 3. The focused lane header and its empty-lane placeholder.
        assert_valid_markup(KanbanView.format_header("Open", 3, focused=True))
        assert_valid_markup(KanbanView.format_header("Open", 3, focused=False))
        assert_valid_markup(KanbanView.format_empty_placeholder(focused=True))
        assert_valid_markup(KanbanView.format_empty_placeholder(focused=False))

        # 4. The highlight *style* attributes, wrapped through the same
        #    ``styled()`` markup path they are emitted through at render time
        #    (frame_style feeds the frame cells; ACTIVE_COLUMN_STYLE wraps the
        #    header). A ``$`` token here would re-introduce the silent no-op.
        assert_valid_markup(styled("x", KanbanView.ACTIVE_COLUMN_STYLE))
        assert_valid_markup(styled("x", KanbanView.SELECTED_FRAME_STYLE))
        assert_valid_markup(styled("x", KanbanView.frame_style(highlighted=True)))
        assert_valid_markup(styled("x", KanbanView.frame_style(highlighted=False)))

    def test_active_lane_header_contrasts_on_light_theme(self, multi_lane_ctx):
        """The active lane header is visible (contrasting fg/bg) on a light theme.

        Regression guard for user bug #2: with the old ``bold cyan`` highlight
        the active lane name ('Open') was thin cyan text that blended into a
        light background and was effectively invisible. The reverse-video
        highlight (:attr:`KanbanView.ACTIVE_COLUMN_STYLE`) now draws the lane
        name as an inverted block whose foreground and background differ, so
        the active lane is always delineated. This renders the real board on a
        light RGB theme (``textual-light``) and asserts the painted header
        segment's effective foreground and background are measurably distinct
        (contrast computed, not a pinned RGB).
        """
        from textual.color import Color

        from doxtr_doto.cli.tui.app import DotoApp, TuiLayout
        from doxtr_doto.cli.tui.widgets import KanbanView

        def luminance(c):
            def chan(v):
                v /= 255.0
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

            return 0.2126 * chan(c.r) + 0.7152 * chan(c.g) + 0.0722 * chan(c.b)

        def contrast(fg, bg):
            lo, hi = sorted((luminance(fg), luminance(bg)))
            return (hi + 0.05) / (lo + 0.05)

        app = DotoApp(multi_lane_ctx)

        async def body():
            async with app.run_test(size=(90, 30)) as pilot:
                await pilot.pause()
                app.scope = DisplayScope.LOCAL  # current-repo content; GLOBAL default shows nothing
                app.refresh_tasks()
                app.theme = "textual-light"
                await pilot.pause()
                for _ in range(6):
                    if app.layout_view is TuiLayout.KANBAN:
                        break
                    app.action_cycle_layout()
                    await pilot.pause()
                await pilot.pause()

                board = app.query_one(KanbanView)
                base_bg = board.background_colors[1]
                base_fg = board.styles.color or Color(255, 255, 255)

                def to_color(rich_color, fallback):
                    if rich_color is None:
                        return fallback
                    trip = rich_color.get_truecolor()
                    return Color(trip.red, trip.green, trip.blue)

                found = None
                for strip in app.screen._compositor.render_strips():
                    text = "".join(seg.text for seg in strip)
                    # Match the active lane HEADER line (box-drawing rule +
                    # the first configured status 'open'), not a status cell.
                    if "\u2500\u2500" not in text or "open" not in text:
                        continue
                    for seg in strip:
                        if "open" not in seg.text or seg.style is None:
                            continue
                        st = seg.style
                        fg = to_color(st.color, base_fg)
                        bg = to_color(st.bgcolor, base_bg)
                        if st.reverse:
                            fg, bg = bg, fg
                        found = (fg, bg)
                        break
                    if found:
                        break

                assert found is not None, "active lane header not painted"
                fg, bg = found
                # The lane name's foreground and background must be distinct -
                # not the identical surface color the old cyan text sat on
                # (which read as invisible). A reverse-video block always
                # yields two different colors here.
                assert fg != bg, (
                    f"active lane header fg == bg ({fg.hex}); the lane name would be invisible"
                )
                # And they must separate by a real margin, not a hairline.
                ratio = contrast(fg, bg)
                assert ratio >= 1.5, (
                    f"active lane header contrast {ratio:.2f} too low (fg={fg.hex}, bg={bg.hex})"
                )

        _run(body())

    # ------------------------------------------------------------------
    # Side-by-side lanes + middle-truncated IDs (board-fit fix).
    # ------------------------------------------------------------------
    def test_four_columns_stay_side_by_side_within_available_width(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Four configured statuses with long IDs: the board must render all
        # four lanes side by side and every board row must fit the available
        # width, so it never wraps into a 2x2 grid.
        statuses = ["open", "in-progress", "blocked", "done"]
        tasks = [
            {"id": "ABCDEFGH-1234567", "status": "open", "title": "alpha"},
            {"id": "WXYZ-9999999999", "status": "in-progress", "title": "beta"},
            {"id": "LONG-TASK-ID-XX", "status": "blocked", "title": "gamma"},
            {"id": "FINAL-TASK-ABCD", "status": "done", "title": "delta"},
        ]
        columns = KanbanView.bucket_by_status(tasks, statuses)
        available = 80  # a common terminal width
        width = KanbanView.column_width(columns, available)
        show_priority = KanbanView.show_priority(columns, width)
        gaps = len(KanbanView.COLUMN_GAP) * (len(columns) - 1)
        # The whole board row (all four columns + gaps) fits the viewport, so
        # the containing Static never line-wraps the row into a grid.
        assert width * len(columns) + gaps <= available
        board = KanbanView.format_board(columns, 0, 0, width=width, show_priority=show_priority)
        lines = board.split("\n")
        for line in lines:
            assert Text.from_markup(line).cell_len <= available
        # All four headers appear on the single header line, left to right.
        header = Text.from_markup(lines[0]).plain
        for name in statuses:
            assert name in header
        assert header.index("open") < header.index("in-progress")
        assert header.index("in-progress") < header.index("blocked")
        assert header.index("blocked") < header.index("done")

    def test_column_width_prefers_even_split_floored_at_min(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        statuses = ["open", "in-progress", "blocked", "done"]
        tasks = [{"id": "ABCDEFGH-1234567", "status": s} for s in statuses]
        columns = KanbanView.bucket_by_status(tasks, statuses)
        gap = len(KanbanView.COLUMN_GAP)
        gaps = gap * (len(columns) - 1)
        # A roomy terminal: the width is the even split (NOT clamped up to the
        # natural min_card_width, which would overflow the viewport).
        available = 120
        width = KanbanView.column_width(columns, available)
        assert width == (available - gaps) // len(columns)
        # A tight terminal: the even split falls below the floor, so the width
        # clamps to MIN_COLUMN_WIDTH (the degenerate edge, kept graceful).
        tight = KanbanView.column_width(columns, 10)
        assert tight == KanbanView.MIN_COLUMN_WIDTH

    def test_truncate_id_cuts_the_middle(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        task_id = "ABCDEFGH-1234567"
        truncated = KanbanView.truncate_id(task_id, 9)
        # The result fits the budget ...
        assert Text(truncated).cell_len <= 9
        # ... the ellipsis is in the MIDDLE (not at the end) ...
        assert KanbanView.ID_ELLIPSIS in truncated
        assert not truncated.endswith(KanbanView.ID_ELLIPSIS)
        assert not truncated.startswith(KanbanView.ID_ELLIPSIS)
        # ... and both the head and the tail of the original survive.
        head, tail = truncated.split(KanbanView.ID_ELLIPSIS)
        assert task_id.startswith(head)
        assert task_id.endswith(tail)
        assert head and tail

    def test_truncate_id_leaves_short_ids_unchanged(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # An ID that already fits its budget is returned verbatim - no
        # ellipsis, no shortening.
        assert KanbanView.truncate_id("T-1", 10) == "T-1"
        assert KanbanView.truncate_id("T-1", 3) == "T-1"
        assert KanbanView.ID_ELLIPSIS not in KanbanView.truncate_id("short", 20)

    def test_truncate_id_degenerate_tiny_budget(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # A non-positive budget yields nothing; a budget too small for even
        # head + ellipsis + tail still never exceeds the budget.
        assert KanbanView.truncate_id("ABCDEFGH", 0) == ""
        tiny = KanbanView.truncate_id("ABCDEFGH", 1)
        assert Text(tiny).cell_len <= 1

    def test_truncate_id_measures_wide_chars_by_visible_width(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Wide (CJK) characters occupy two columns each, so truncation must
        # honor visible width, not code-point count.
        wide_id = "\u4f60\u597d\u4e16\u754c\u4f60\u597d"  # 6 chars = 12 columns
        truncated = KanbanView.truncate_id(wide_id, 7)
        assert Text(truncated).cell_len <= 7
        assert KanbanView.ID_ELLIPSIS in truncated

    def test_truncate_id_is_overridable_without_touching_layout(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        class _ThemedKanbanView(KanbanView):
            """A themed view overriding ONLY the ID-truncation seam."""

            ID_ELLIPSIS = "**"

            @classmethod
            def truncate_id(cls, task_id: str, max_width: int) -> str:
                # A trivial override proving the seam is reachable alone: tag
                # every shortened ID and still respect the width budget.
                if cls._cell_width(task_id) <= max_width:
                    return task_id
                return cls._cell_slice(task_id, max_width)

        # The override is used end-to-end by format_card_first_line's budget,
        # and the layout math (column_width/min_card_width) is untouched.
        line = _ThemedKanbanView.format_card_first_line(
            {"id": "ABCDEFGH-1234567", "due": "2099-01-15"},
            show_priority=False,
            max_width=20,
        )
        plain = Text.from_markup(line).plain
        assert plain.startswith("ABC")
        # The themed override cuts from the end (no middle ellipsis), proving
        # the seam swapped the whole truncation policy without layout changes.
        assert "**" not in plain
        # The base class is unaffected (its truncate_id still cuts the middle).
        base = KanbanView.truncate_id("ABCDEFGH-1234567", 9)
        assert KanbanView.ID_ELLIPSIS in base

    def test_first_line_middle_truncates_id_to_fit_budget(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # With a max_width budget the first line's ID is middle-truncated so
        # the whole line fits, while the due date is left intact.
        line = KanbanView.format_card_first_line(
            {"id": "ABCDEFGH-1234567", "due": "2099-01-15"},
            show_priority=False,
            max_width=22,
        )
        plain = Text.from_markup(line).plain
        assert Text.from_markup(line).cell_len <= 22
        # The due date is unchanged (only the ID was shortened).
        assert "2099-01-15" in plain
        # The ID was middle-truncated (ellipsis present, head + tail kept).
        assert KanbanView.ID_ELLIPSIS in plain
        assert plain.startswith("ABC")

    def test_first_line_without_budget_keeps_full_id(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # No budget (natural-width measurement, e.g. min_card_width) leaves the
        # ID intact so the width authority measures the full first line.
        line = KanbanView.format_card_first_line({"id": "ABCDEFGH-1234567"}, show_priority=False)
        assert "ABCDEFGH-1234567" in Text.from_markup(line).plain

    def test_rendered_card_middle_truncates_long_id_to_column(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Through the full format_card pipeline a long ID is middle-truncated
        # to the card's inner width and the first line still fits the column.
        width = 18
        card = KanbanView.format_card(
            {"id": "ABCDEFGH-1234567", "title": "body"},
            highlighted=False,
            width=width,
            show_priority=False,
        )
        # Every row fits the column exactly (no spill).
        for row in card:
            assert Text.from_markup(row).cell_len == width
        # The ID row (one below the top border) carries a middle ellipsis.
        id_row = Text.from_markup(card[1]).plain
        assert KanbanView.ID_ELLIPSIS in id_row
        assert id_row.lstrip(KanbanView.FRAME_CHARS[5]).strip().startswith("ABC")

    def test_running_card_keeps_id_nonempty_at_min_column_floor(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # A RUNNING task WITH a due date at the MIN_COLUMN_WIDTH floor: the
        # running indicator + due date can otherwise consume the whole inner
        # width, dropping the ID entirely. The budget floor keeps the ID
        # non-empty (at least a leading char / ellipsis) when ANY room is left.
        width = KanbanView.MIN_COLUMN_WIDTH
        inner = width - KanbanView.frame_overhead()
        task = {"id": "ABCDEFGH-1234567", "due": "2099-01-15", "_running": True}
        first = KanbanView.format_card_first_line(task, show_priority=False, max_width=inner)
        plain = Text.from_markup(first).plain
        # The ID portion is non-empty: a real ID char survives before the gap.
        assert "A" in plain
        # The running indicator is still present (it is not what was dropped).
        assert "\u25b6" in plain
        # Through the full card pipeline the ID row is still non-empty and the
        # row never spills past the column width.
        card = KanbanView.format_card(task, highlighted=False, width=width, show_priority=False)
        for row in card:
            assert Text.from_markup(row).cell_len == width
        id_row = Text.from_markup(card[1]).plain
        # Strip the frame borders and the running indicator; a leading ID char
        # must remain (the ID is never completely blank).
        stripped = id_row.strip(KanbanView.FRAME_CHARS[5]).strip()
        assert "A" in stripped

    def test_truncate_id_tiny_budget_keeps_leading_id_char(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # When the budget is at or below the ellipsis width and the ID is
        # longer than the budget, the tiny-budget branch keeps a LEADING ID
        # prefix (real characters) rather than a lone ellipsis.
        task_id = "ABCDEFGH-1234567"
        ellipsis_w = KanbanView._cell_width(KanbanView.ID_ELLIPSIS)
        assert ellipsis_w == 1
        tiny = KanbanView.truncate_id(task_id, 1)
        # It respects the width bound ...
        assert Text(tiny).cell_len <= 1
        # ... and shows a leading ID character, NOT a bare ellipsis.
        assert tiny == "A"
        assert tiny != KanbanView.ID_ELLIPSIS

    def test_first_line_gap_is_honored_and_keeps_budget_correct(self):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        class _WideGapKanbanView(KanbanView):
            """A themed view widening ONLY the first-line separator."""

            FIRST_LINE_GAP = "    "  # four spaces instead of two

        task = {"id": "ABCDEFGH-1234567", "due": "2099-01-15"}
        max_width = 24
        base = Text.from_markup(
            KanbanView.format_card_first_line(task, show_priority=False, max_width=max_width)
        ).plain
        wide = Text.from_markup(
            _WideGapKanbanView.format_card_first_line(
                task, show_priority=False, max_width=max_width
            )
        ).plain
        # The rendered separator changed: the wider gap puts four spaces
        # between the ID and the due date (the base uses two).
        assert "    " + "2099-01-15" in wide
        assert "  " + "2099-01-15" in base
        assert "    " + "2099-01-15" not in base
        # The truncation budget stays correct: the wider gap leaves less room
        # for the ID, so the themed ID is no longer than the base's, and the
        # whole first line still fits the inner width (no spill).
        for line in (base, wide):
            assert len(line) <= max_width
        base_id = base.split("  ")[0]
        wide_id = wide.split("    ")[0]
        assert len(wide_id) <= len(base_id)
        # The due date survives intact in both (only the ID absorbs the gap).
        assert "2099-01-15" in base
        assert "2099-01-15" in wide


class TestCalendarView:
    """Pure-logic tests for the calendar bucketing / rendering classmethods."""

    def test_bucket_by_due_groups_by_date(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        tasks = [
            {"id": "A", "due": "2099-01-15"},
            {"id": "B", "due": "2099-01-15"},
            {"id": "C", "due": "2099-02-01"},
        ]
        buckets = CalendarView.bucket_by_due(tasks)
        assert [t["id"] for t in buckets["2099-01-15"]] == ["A", "B"]
        assert [t["id"] for t in buckets["2099-02-01"]] == ["C"]

    def test_bucket_by_due_handles_no_due_date(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        tasks = [
            {"id": "A", "due": "2099-01-15"},
            {"id": "B"},  # missing due
            {"id": "C", "due": ""},  # empty due
            {"id": "D", "due": "not-a-date"},  # unparseable due
        ]
        buckets = CalendarView.bucket_by_due(tasks)
        undated = [t["id"] for t in buckets[CalendarView.NO_DUE_KEY]]
        # Missing, empty, and unparseable all land in the no-due bucket.
        assert undated == ["B", "C", "D"]

    def test_day_detail_lists_no_due_bucket(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        buckets = CalendarView.bucket_by_due(
            [{"id": "A", "due": "2099-01-15", "status": "open"}, {"id": "B", "status": "open"}]
        )
        detail = CalendarView.format_day_detail(buckets, "2099-01-15")
        assert "A" in detail
        assert "No due date (1)" in detail
        assert "B" in detail

    def test_calendar_grid_renders_month(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        buckets = CalendarView.bucket_by_due([{"id": "A", "due": "2099-01-15"}])
        grid = CalendarView.format_calendar(buckets, "2099-01-15", 2099, 1)
        assert "January 2099" in grid
        assert "Mo Tu We Th Fr Sa Su" in grid

    def test_grid_line_count_matches_header_plus_weeks(self):
        import calendar as _cal

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.year, view.month = 2099, 1
        weeks = _cal.Calendar().monthdayscalendar(2099, 1)
        # The pinned grid region spans the header lines plus one per week row.
        assert view.grid_line_count() == CalendarView.GRID_HEADER_LINES + len(weeks)
        # Before the grid is populated there is no grid region.
        assert CalendarView().grid_line_count() == 0

    def test_selected_id_follows_region_cursor(self):
        """Feature A/B: selected_id returns the focused region's cursor task."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild(
            [
                {"id": "D1", "due": "2099-01-15"},
                {"id": "D2", "due": "2099-01-15"},
                {"id": "N1"},
                {"id": "N2"},
            ],
            today=date(2099, 1, 15),
        )
        # Grid region: the first task due on the selected day (original).
        assert view.focus_region == CalendarView.REGION_GRID
        assert view.selected_id() == "D1"
        # Due region: the highlighted due task.
        view.set_focus_region(CalendarView.REGION_DUE)
        assert view.selected_id() == "D1"
        view.move_cursor(1)
        assert view.region_cursor == 1
        assert view.selected_id() == "D2"
        # No-due region: the highlighted undated task.
        view.set_focus_region(CalendarView.REGION_NO_DUE)
        assert view.selected_id() == "N1"
        view.move_cursor(1)
        assert view.selected_id() == "N2"

    def test_move_cursor_overflow_advances_region(self):
        """Feature A: j/k past a list's end flows into the adjacent region."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild(
            [{"id": "D1", "due": "2099-01-15"}, {"id": "N1"}],
            today=date(2099, 1, 15),
        )
        # From the single-item Due list, moving down flows into No-due.
        view.set_focus_region(CalendarView.REGION_DUE)
        view.move_cursor(1)
        assert view.focus_region == CalendarView.REGION_NO_DUE
        assert view.region_cursor == 0
        # From the No-due list, moving up flows back into the Due list.
        view.move_cursor(-1)
        assert view.focus_region == CalendarView.REGION_DUE
        # From the Due list, moving up flows into the grid (week navigation).
        view.move_cursor(-1)
        assert view.focus_region == CalendarView.REGION_GRID

    def test_grid_region_move_cursor_moves_a_week(self):
        """Feature A: j/k in the grid region keep moving a whole week."""
        from datetime import date, timedelta

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild([{"id": "A", "due": "2099-01-15"}], today=date(2099, 1, 15))
        start = date.fromisoformat(view.selected)
        assert view.focus_region == CalendarView.REGION_GRID
        view.move_cursor(1)  # down one grid row
        assert date.fromisoformat(view.selected) == start + timedelta(days=7)

    def test_move_cursor_to_edge_in_grid_jumps_month_bounds(self):
        """Shift+Up/Down in the grid region jump to the first/last day."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild([{"id": "A", "due": "2099-01-15"}], today=date(2099, 1, 15))
        assert view.focus_region == CalendarView.REGION_GRID
        # Shift+Down jumps to the last day of the visible month (Jan has 31).
        view.move_cursor_to_edge(True)
        assert date.fromisoformat(view.selected) == date(2099, 1, 31)
        # Shift+Up jumps to the first day of the month.
        view.move_cursor_to_edge(False)
        assert date.fromisoformat(view.selected) == date(2099, 1, 1)

    def test_move_cursor_to_edge_in_due_region_jumps_list(self):
        """Shift+Up/Down in a list region jump the per-task cursor."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild(
            [
                {"id": "D1", "due": "2099-01-15"},
                {"id": "D2", "due": "2099-01-15"},
                {"id": "D3", "due": "2099-01-15"},
            ],
            today=date(2099, 1, 15),
        )
        view.set_focus_region(CalendarView.REGION_DUE)
        assert view.region_cursor == 0
        # Shift+Down jumps to the last Due task; the region never changes.
        view.move_cursor_to_edge(True)
        assert view.focus_region == CalendarView.REGION_DUE
        assert view.region_cursor == 2
        assert view.selected_id() == "D3"
        # Shift+Up jumps back to the first Due task.
        view.move_cursor_to_edge(False)
        assert view.focus_region == CalendarView.REGION_DUE
        assert view.region_cursor == 0
        assert view.selected_id() == "D1"

    def test_move_cursor_to_edge_empty_list_region_is_no_op(self):
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        # No tasks due on the selected day: the Due list is empty.
        view.rebuild([{"id": "N1"}], today=date(2099, 1, 15))
        view.set_focus_region(CalendarView.REGION_DUE)
        assert view.region_tasks() == []
        view.move_cursor_to_edge(True)
        assert view.region_cursor == 0
        view.move_cursor_to_edge(False)
        assert view.region_cursor == 0
        assert view.selected_id() is None

    def test_cycle_region_steps_off_ends(self):
        """Feature A: cycle_region signals when it runs off either end."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild([{"id": "A", "due": "2099-01-15"}, {"id": "B"}], today=date(2099, 1, 15))
        # Forward through the regions returns 0 until it steps off the end.
        assert view.cycle_region(1) == 0  # grid -> Due
        assert view.focus_region == CalendarView.REGION_DUE
        assert view.cycle_region(1) == 0  # Due -> No-due
        assert view.focus_region == CalendarView.REGION_NO_DUE
        assert view.cycle_region(1) == 1  # No-due -> (details); region unchanged
        assert view.focus_region == CalendarView.REGION_NO_DUE
        # Reverse off the start of the regions (grid) signals -1.
        view.set_focus_region(CalendarView.REGION_GRID)
        assert view.cycle_region(-1) == -1
        assert view.focus_region == CalendarView.REGION_GRID

    def test_assign_task_id_only_in_no_due_region(self):
        """Feature C: assign_task_id surfaces only the no-due cursor task."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild(
            [{"id": "D1", "due": "2099-01-15"}, {"id": "N1"}],
            today=date(2099, 1, 15),
        )
        # Grid / Due regions: nothing to assign.
        assert view.assign_task_id() is None
        view.set_focus_region(CalendarView.REGION_DUE)
        assert view.assign_task_id() is None
        # No-due region: the highlighted undated task.
        view.set_focus_region(CalendarView.REGION_NO_DUE)
        assert view.assign_task_id() == "N1"

    def test_format_day_detail_highlights_active_region_cursor(self):
        """Feature A/B: the active region's cursor task renders highlighted."""
        from doxtr_doto.cli.tui.widgets import CalendarView

        buckets = CalendarView.bucket_by_due(
            [
                {"id": "D1", "due": "2099-01-15", "status": "open"},
                {"id": "N1", "status": "open"},
            ]
        )
        # Highlight the Due cursor (index 0).
        due = CalendarView.format_day_detail(buckets, "2099-01-15", CalendarView.REGION_DUE, 0)
        assert "[reverse]  [bold]D1[/bold]" in due
        assert "[reverse]  [bold]N1[/bold]" not in due
        # Highlight the No-due cursor (index 0).
        no_due = CalendarView.format_day_detail(
            buckets, "2099-01-15", CalendarView.REGION_NO_DUE, 0
        )
        assert "[reverse]  [bold]N1[/bold]" in no_due
        assert "[reverse]  [bold]D1[/bold]" not in no_due
        # The grid region (default) highlights nothing.
        plain = CalendarView.format_day_detail(buckets, "2099-01-15")
        assert "[reverse]" not in plain

    def test_move_day_in_due_region_retargets_and_clamps_cursor(self):
        """Fix #8: h/l while in Due re-targets the day and re-clamps cursor."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        tasks = [
            {"id": "D1", "due": "2099-01-15"},
            {"id": "D2", "due": "2099-01-15"},
            {"id": "N1"},  # the next day (01-16) has no due tasks
        ]
        view.rebuild(tasks, today=date(2099, 1, 15))
        view.set_focus_region(CalendarView.REGION_DUE)
        view.move_cursor(1)  # cursor on D2 (index 1)
        assert view.region_cursor == 1
        assert view.selected == "2099-01-15"
        # h/l (move_day) always re-targets the selected day even in a list
        # region; the next day has zero due tasks so the cursor re-clamps.
        view.move_day(1)
        view.rebuild(tasks, today=date(2099, 1, 16))
        assert view.selected == "2099-01-16"
        # region_cursor stays a valid index into the (now empty) Due list.
        assert view.focus_region == CalendarView.REGION_DUE
        assert view.region_cursor == 0
        assert view.selected_id() is None

    def test_selected_id_and_assign_none_on_empty_due(self):
        """Fix #9b: empty Due region reports no selection / nothing to assign."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        # Selected day (01-20) has no due tasks; only an undated task exists.
        view.rebuild([{"id": "N1"}], today=date(2099, 1, 20))
        view.set_focus_region(CalendarView.REGION_DUE)
        assert view.region_tasks() == []
        assert view.selected_id() is None
        assert view.assign_task_id() is None

    def test_region_cursor_clamps_when_list_shrinks(self):
        """Fix #9c: a rebuild with fewer tasks re-clamps the region cursor."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        view.rebuild([{"id": "N1"}, {"id": "N2"}, {"id": "N3"}], today=date(2099, 1, 15))
        view.set_focus_region(CalendarView.REGION_NO_DUE)
        view.move_cursor(1)
        view.move_cursor(1)  # cursor on N3 (index 2)
        assert view.region_cursor == 2
        assert view.selected_id() == "N3"
        # Rebuild with a shorter no-due list: the cursor must re-clamp into
        # range and still resolve to a valid task.
        view.rebuild([{"id": "N1"}], today=date(2099, 1, 15))
        assert view.focus_region == CalendarView.REGION_NO_DUE
        assert view.region_cursor == 0
        assert view.selected_id() == "N1"

    def test_calendar_select_id_targets_dated_and_no_due_tasks(self):
        """``select_id`` focuses the region/day holding the task.

        The calendar's :meth:`select_id` (the view seam the app-level
        ``select_task`` delegates to for auto-selecting a freshly created
        task) must handle both buckets: a dated task re-targets the selected
        day and focuses the Due list, while an undated task focuses the No-due
        list. Mirrors the list/kanban ``select_id`` tests above but asserts
        the calendar's region/day/cursor state so ``selected_id()`` resolves
        to the chosen task.
        """
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        view = CalendarView()
        # A dated task (due 2099-02-10) plus an undated one; build on a
        # different day/month so select_id has to re-target the grid.
        view.rebuild(
            [
                {"id": "D1", "due": "2099-02-10"},
                {"id": "N1"},
            ],
            today=date(2099, 1, 15),
        )
        # Selecting the dated task re-targets the day/month, focuses the Due
        # list, and points the region cursor at it.
        assert view.select_id("D1") is True
        assert view.focus_region == CalendarView.REGION_DUE
        assert view.selected == "2099-02-10"
        assert view.year == 2099
        assert view.month == 2
        assert view.region_cursor == 0
        assert view.selected_id() == "D1"
        # Selecting the undated task focuses the No-due list instead.
        assert view.select_id("N1") is True
        assert view.focus_region == CalendarView.REGION_NO_DUE
        assert view.selected_id() == "N1"
        # A missing id is a no-op that returns False.
        assert view.select_id("NONEXISTENT") is False


class TestTimeView:
    """Pure-logic tests for the time-view day navigation."""

    def _view_with_days(self, count):
        from datetime import date, timedelta

        from doxtr_doto.cli.tui.widgets import TimeView

        view = TimeView()
        # Newest day first, matching rebuild's ordering.
        view.days = [date(2099, 1, 10) - timedelta(days=i) for i in range(count)]
        view._day_rows = {d.isoformat(): [] for d in view.days}
        view._day_work = {}
        view._totals = (0, 0, 0)
        view.cursor = 0
        return view

    def test_move_cursor_to_edge_jumps_to_last_and_first_day(self):
        view = self._view_with_days(5)
        assert view.cursor == 0
        first_day = view.selected_day()
        # Shift+Down jumps to the last (oldest) day.
        view.move_cursor_to_edge(True)
        assert view.cursor == 4
        assert view.selected_day() == view.days[4]
        # Shift+Up jumps back to the first (newest) day.
        view.move_cursor_to_edge(False)
        assert view.cursor == 0
        assert view.selected_day() == first_day

    def test_move_cursor_to_edge_empty_is_no_op(self):
        view = self._view_with_days(0)
        view.move_cursor_to_edge(True)
        assert view.cursor == 0
        view.move_cursor_to_edge(False)
        assert view.cursor == 0
        assert view.selected_day() is None


class TestSmartScroll:
    """Unit tests for the shared smart-scroll algorithm (Feature 4).

    Exercises :meth:`AltLayoutView.target_scroll_y` directly through a tiny
    stub that fixes the viewport geometry (max scroll, current offset, height)
    the method reads, so the margin trigger, the jump, and configurability are
    tested without a live terminal.
    """

    def _stub(self, *, scroll_y, height, max_scroll, margin=None, jump=None, span=None):
        """Return an ``AltLayoutView``-like stub with a fixed viewport geometry.

        ``scroll_y`` / ``max_scroll_y`` / ``size`` are read-only Textual
        properties on the real widget, so this builds a lightweight subclass
        that overrides them with the fixed values the algorithm reads. Only
        :meth:`target_scroll_y` is exercised, which needs nothing else. Pass
        ``span`` to simulate a multi-line / oversized cursor item (as kanban
        cards do via :meth:`cursor_span`).
        """
        from types import SimpleNamespace

        from doxtr_doto.cli.tui.widgets import AltLayoutView

        class _StubView(AltLayoutView):
            scroll_y = property(lambda self: scroll_y)
            max_scroll_y = property(lambda self: max_scroll)
            size = property(lambda self: SimpleNamespace(height=height, width=80))

        if margin is not None:
            _StubView.SCROLL_MARGIN = margin
        if jump is not None:
            _StubView.SCROLL_JUMP = jump
        if span is not None:
            _StubView.cursor_span = lambda self, _s=span: _s
        return _StubView.__new__(_StubView)

    def test_no_scroll_in_the_middle_of_the_frame(self):
        # Cursor well away from both edges (margin=2): no scroll.
        view = self._stub(scroll_y=0, height=10, max_scroll=50)
        assert view.target_scroll_y(cursor_line=5, previous_line=4) is None

    def test_no_scroll_when_content_fits(self):
        # Nothing to scroll (max_scroll == 0): always None.
        view = self._stub(scroll_y=0, height=10, max_scroll=0)
        assert view.target_scroll_y(cursor_line=9, previous_line=8) is None

    def test_jump_when_crossing_bottom_margin(self):
        # Viewport shows lines 0..9; margin=2 so the bottom trigger is line 8.
        # Moving the cursor to line 8 (within the margin) jumps SCROLL_JUMP=5
        # extra rows past the bottom edge.
        view = self._stub(scroll_y=0, height=10, max_scroll=50)
        target = view.target_scroll_y(cursor_line=8, previous_line=7)
        # cursor - height + 1 + jump = 8 - 10 + 1 + 5 = 4.
        assert target == 4

    def test_jump_when_crossing_top_margin(self):
        # Viewport shows lines 20..29; margin=2 so the top trigger is line 21.
        # Moving up to line 21 jumps SCROLL_JUMP=5 rows above the cursor.
        view = self._stub(scroll_y=20, height=10, max_scroll=50)
        target = view.target_scroll_y(cursor_line=21, previous_line=22)
        # cursor - jump = 21 - 5 = 16.
        assert target == 16

    def test_jump_is_clamped_to_scroll_range(self):
        # A jump that would overshoot the content is clamped to max_scroll.
        view = self._stub(scroll_y=0, height=10, max_scroll=3)
        target = view.target_scroll_y(cursor_line=9, previous_line=8)
        assert target == 3  # clamped to max_scroll

    def test_scroll_jump_is_configurable(self):
        # Overriding SCROLL_JUMP changes how far the view hops.
        default = self._stub(scroll_y=0, height=10, max_scroll=50)
        custom = self._stub(scroll_y=0, height=10, max_scroll=50, jump=20)
        d = default.target_scroll_y(cursor_line=8, previous_line=7)
        c = custom.target_scroll_y(cursor_line=8, previous_line=7)
        # Larger jump -> larger target offset.
        assert c > d
        assert c == 8 - 10 + 1 + 20

    def test_scroll_margin_is_configurable(self):
        # With margin=5, a cursor at line 6 (within 5 of the bottom edge 9)
        # triggers a scroll that the default margin=2 would not.
        wide_margin = self._stub(scroll_y=0, height=10, max_scroll=50, margin=5)
        default = self._stub(scroll_y=0, height=10, max_scroll=50)
        assert default.target_scroll_y(cursor_line=6, previous_line=5) is None
        assert wide_margin.target_scroll_y(cursor_line=6, previous_line=5) is not None

    def test_within_bottom_margin_but_moving_up_does_not_snap_down(self):
        # Fix 4: the cursor is within the bottom margin (line 8 of a 0..9
        # frame, margin=2 so the bottom trigger is line 8) but the move is
        # *upward* (previous_line=9 -> cursor_line=8). Pre-fix the ungated
        # bottom branch fired and returned a downward target (4), snapping the
        # frame against the move direction. With the branch gated on
        # ``moving_down`` the move away from the bottom edge no longer scrolls:
        # it returns None (and so would never move the frame downward).
        view = self._stub(scroll_y=0, height=10, max_scroll=50)
        target = view.target_scroll_y(cursor_line=8, previous_line=9)
        assert target is None or target <= 0

    def test_within_top_margin_but_moving_down_does_not_snap_up(self):
        # The symmetric case: within the top margin (line 21 of a 20..29 frame,
        # margin=2 so the top trigger is line 21) but moving *down*
        # (previous_line=20 -> cursor_line=21). The top branch is gated on
        # ``not moving_down`` so the move away from the top edge does not snap
        # the frame up against the direction.
        view = self._stub(scroll_y=20, height=10, max_scroll=50)
        target = view.target_scroll_y(cursor_line=21, previous_line=20)
        assert target is None or target >= 20

    def test_span_one_preserves_single_line_look_ahead(self):
        # Regression guard for the ``span > 1`` gate: a one-line cursor item
        # (list / calendar) must still perform the SCROLL_JUMP look-ahead past
        # the edge it is moving toward. If someone drops the span==1 branch
        # this value would change. Moving down into line 8 (frame 0..9,
        # margin=2) jumps to 8 - 10 + 1 + 5 = 4.
        view = self._stub(scroll_y=0, height=10, max_scroll=50, span=1)
        assert view.target_scroll_y(cursor_line=8, previous_line=7) == 4
        # Moving up into line 21 (frame 20..29) jumps to 21 - 5 = 16.
        up = self._stub(scroll_y=20, height=10, max_scroll=50, span=1)
        assert up.target_scroll_y(cursor_line=21, previous_line=22) == 16

    def test_oversized_item_aligns_top_to_viewport(self):
        # A single item taller than the viewport (span=12 > height=8) cannot
        # fit, so the whole-span clamp deliberately aligns the item's TOP to
        # the viewport top (shows the start of the oversized card) rather than
        # pushing it off either edge. Target == cursor_line regardless of the
        # SCROLL_JUMP look-ahead.
        down = self._stub(scroll_y=0, height=8, max_scroll=50, span=12)
        assert down.target_scroll_y(cursor_line=10, previous_line=5) == 10
        up = self._stub(scroll_y=20, height=8, max_scroll=50, span=12)
        assert up.target_scroll_y(cursor_line=10, previous_line=15) == 10

    def test_multiline_down_keeps_whole_span_on_screen(self):
        # A multi-line item that fits (span=5, height=10) moving down into the
        # bottom margin must land with its BOTTOM line on screen. Cursor at
        # line 7 -> item occupies 7..11; the clamp keeps item_bottom (11)
        # inside the frame [target .. target+9].
        view = self._stub(scroll_y=0, height=10, max_scroll=50, span=5)
        target = view.target_scroll_y(cursor_line=7, previous_line=6)
        assert target is not None
        item_bottom = 7 + 5 - 1
        assert target <= 7  # item top on screen
        assert item_bottom <= target + 10 - 1  # item bottom on screen

    def test_multiline_up_keeps_whole_span_on_screen(self):
        # Symmetric P0 regression: a tall card walking UP into a small frame
        # must keep its BOTTOM edge on screen, not just its top. Repro from the
        # correctness review: height=12, span=10, frame top=12, card top line
        # 11 (occupies 11..20). Pre-fix the up-path lacked the symmetric bottom
        # guard and returned target=6 (frame 6..17), pushing line 20 three rows
        # below the frame. The guard must keep item_bottom (20) on screen.
        view = self._stub(scroll_y=12, height=12, max_scroll=50, span=10)
        target = view.target_scroll_y(cursor_line=11, previous_line=21)
        assert target is not None
        item_bottom = 11 + 10 - 1
        assert target <= 11  # item top on screen
        assert item_bottom <= target + 12 - 1  # item bottom on screen (was failing)

    # ------------------------------------------------------------------
    # ensure_cursor_visible / target_visible_scroll_y: the discontinuous-jump
    # reposition seam (last unchecked feature). These exercise the direction-
    # independent target computation directly through the same geometry stub.
    # ------------------------------------------------------------------
    def test_visible_target_none_when_span_already_on_screen(self):
        # A one-line cursor item already inside the viewport (frame 10..19,
        # cursor at line 12) needs no reposition: target_visible_scroll_y
        # returns None (minimal scroll - the frame does not move).
        view = self._stub(scroll_y=10, height=10, max_scroll=50)
        assert view.target_visible_scroll_y(cursor_line=12) is None

    def test_visible_target_scrolls_up_when_cursor_above_frame(self):
        # The core bug: the cursor lands ABOVE the current frame (frame
        # 30..39, cursor at line 0 - e.g. after switching to a one-card lane
        # whose card is at the top). Direction-free reposition must pull the
        # frame up so the item's top (line 0) is visible: offset == 0.
        view = self._stub(scroll_y=30, height=10, max_scroll=50)
        assert view.target_visible_scroll_y(cursor_line=0) == 0

    def test_visible_target_scrolls_down_when_cursor_below_frame(self):
        # The cursor lands BELOW the current frame (frame 0..9, cursor at line
        # 40). Reposition must push the frame down so the item's bottom is on
        # screen; with span=1 the deepest offset keeping line 40 visible is
        # 40 - 10 + 1 = 31.
        view = self._stub(scroll_y=0, height=10, max_scroll=50)
        assert view.target_visible_scroll_y(cursor_line=40) == 31

    def test_visible_target_keeps_whole_card_span_on_screen(self):
        # A multi-line card (span=5) landing below the frame (frame 0..9,
        # card top line 40 -> occupies 40..44) must keep its BOTTOM line on
        # screen: deepest offset is item_bottom - height + 1 = 44 - 10 + 1 = 35.
        view = self._stub(scroll_y=0, height=10, max_scroll=50, span=5)
        target = view.target_visible_scroll_y(cursor_line=40)
        assert target == 35
        item_bottom = 40 + 5 - 1
        assert target <= 40  # card top on screen
        assert item_bottom <= target + 10 - 1  # card bottom on screen

    def test_visible_target_oversized_card_aligns_top(self):
        # An oversized card (span=12 > height=8) cannot fit; the reposition
        # aligns its top to the viewport top (shows the start) regardless of
        # the current offset, mirroring target_scroll_y's oversized branch.
        view = self._stub(scroll_y=30, height=8, max_scroll=50, span=12)
        assert view.target_visible_scroll_y(cursor_line=10) == 10

    def test_visible_target_clamped_to_scroll_range(self):
        # A reposition that would overshoot the content is clamped to
        # max_scroll (the frame cannot scroll past the end).
        view = self._stub(scroll_y=0, height=10, max_scroll=3)
        assert view.target_visible_scroll_y(cursor_line=40) == 3

    def test_visible_target_none_when_content_fits(self):
        # Nothing to scroll (max_scroll == 0): no reposition.
        view = self._stub(scroll_y=0, height=10, max_scroll=0)
        assert view.target_visible_scroll_y(cursor_line=5) is None


class TestLayoutViews:
    """Pilot-driven tests of the configurable TUI layout views."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        # Render the single current repo's tasks; pin LOCAL scope (the app now
        # defaults to GLOBAL, which would show nothing for the unregistered
        # current repo these fixtures use).
        app.scope = DisplayScope.LOCAL
        return app

    def test_cycle_layout_changes_active_view(self, ctx):
        from doxtr_doto.enums import TuiLayout

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE
                await pilot.press("v")
                await pilot.pause()
                assert app.layout_view == TuiLayout.LIST
                await pilot.press("v")
                await pilot.pause()
                assert app.layout_view == TuiLayout.KANBAN
                await pilot.press("v")
                await pilot.pause()
                assert app.layout_view == TuiLayout.CALENDAR
                await pilot.press("v")
                await pilot.pause()
                assert app.layout_view == TuiLayout.TIME
                await pilot.press("v")  # wraps back to table
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE

        _run(body())

    def test_cycle_layout_prev_changes_active_view(self, ctx):
        from doxtr_doto.enums import TuiLayout

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE
                await pilot.press("V")  # wraps back to the last layout
                await pilot.pause()
                assert app.layout_view == TuiLayout.TIME
                await pilot.press("V")
                await pilot.pause()
                assert app.layout_view == TuiLayout.CALENDAR
                await pilot.press("V")
                await pilot.pause()
                assert app.layout_view == TuiLayout.KANBAN
                await pilot.press("V")
                await pilot.pause()
                assert app.layout_view == TuiLayout.LIST
                await pilot.press("V")
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE

        _run(body())

    def test_cycle_layout_prev_is_inverse_of_forward(self, ctx):
        from doxtr_doto.enums import TuiLayout

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE
                # Forward then prev returns to the original layout.
                app.action_cycle_layout()
                await pilot.pause()
                assert app.layout_view == TuiLayout.LIST
                app.action_cycle_layout_prev()
                await pilot.pause()
                assert app.layout_view == TuiLayout.TABLE
                # Prev from the first layout wraps to the last.
                app.action_cycle_layout_prev()
                await pilot.pause()
                assert app.layout_view == TuiLayout.TIME

        _run(body())

    def test_each_view_renders_populated(self, ctx):
        from doxtr_doto.cli.tui.widgets import CalendarView, KanbanView, ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                assert app.query_one(ListView).display is True
                assert app.query_one(ListView).row_ids == ["T-001", "T-002"]
                await pilot.press("v")  # kanban
                await pilot.pause()
                assert app.query_one(KanbanView).display is True
                assert any(items for _n, items in app.query_one(KanbanView).columns)
                await pilot.press("v")  # calendar
                await pilot.pause()
                assert app.query_one(CalendarView).display is True

        _run(body())

    def test_list_view_renders_multiline_authored_title_on_single_line(self, ctx):
        """The list view renders a (multi-line-authored) title on one line.

        A doto directive title written across continuation lines keeps its
        embedded newlines and continuation indentation until the directive
        normalizes it (:func:`doxtr_doto.utils.normalize_whitespace`). This
        test pins the view contract from both sides: the raw multi-line title
        would render with an embedded newline (the bug), while the normalized
        title the directive stores renders as one contiguous compact line.
        """
        from doxtr_doto.cli.tui.widgets import ListView
        from doxtr_doto.utils import normalize_whitespace

        # The raw argument as docutils hands it to the directive: embedded
        # newlines plus continuation indentation.
        raw_title = (
            "Assess whether GitLab's SCIM 2.0 implementation is still\n"
            "   incomplete (see GitLab work items 597897 and 452118) as a "
            "contributing\n   root cause"
        )
        expected = (
            "Assess whether GitLab's SCIM 2.0 implementation is still "
            "incomplete (see GitLab work items 597897 and 452118) as a "
            "contributing root cause"
        )

        def _task(title: str) -> dict[str, object]:
            return {
                "id": "MULTI-001",
                "title": title,
                "status": "open",
                "priority": "high",
                "tags": [],
            }

        # Guard: the un-normalized raw title breaks the single-line layout,
        # which is exactly the bug the directive normalization prevents.
        raw_line = ListView.format_line(_task(raw_title), highlighted=False)
        assert "\n" in raw_line

        # The directive stores the normalized title; the view then renders it
        # verbatim on one line with the words left contiguous.
        line = ListView.format_line(_task(normalize_whitespace(raw_title)), highlighted=False)
        assert "\n" not in line
        assert expected in line

    def test_each_view_renders_empty_store(self, empty_ctx):
        from doxtr_doto.cli.tui.widgets import CalendarView, KanbanView, ListView

        app = self._app(empty_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                list_view = app.query_one(ListView)
                assert list_view.row_ids == []
                assert list_view.selected_id() is None
                assert "No tasks." in list_view.rendered_text()
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                # Every configured status column is present but empty, each
                # rendering the empty-column placeholder.
                assert board.columns
                assert all(items == [] for _name, items in board.columns)
                assert "(empty)" in board.rendered_text()
                await pilot.press("v")  # calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                assert calendar.selected_tasks() == []
                assert "(nothing due)" in calendar.rendered_text()
                await pilot.press("v")  # time view
                await pilot.pause()

        _run(body())

    def test_calendar_navigation_via_actions(self, ctx):
        from datetime import date, timedelta

        from doxtr_doto.cli.tui.widgets import CalendarView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                start = date.fromisoformat(calendar.selected)
                # h/l move a single day through the app action path.
                await pilot.press("l")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start + timedelta(days=1)
                await pilot.press("h")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start
                # j/k move a whole week via _move_cursor -> move_cursor.
                await pilot.press("j")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start + timedelta(days=7)
                await pilot.press("k")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start

        _run(body())

    def test_kanban_hl_navigate_lanes_without_moving_card(self, ctx, store_file):
        """Feature A: h/l navigate the kanban selection across lanes.

        h/l (mirroring left/right arrows) relocate the *selection* to the
        adjacent swim lane without changing any task's status; a move off the
        left edge is a no-op (no wrap).
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.col == 0
                # At the left edge, h is a no-op (no column to the left).
                await pilot.press("h")
                await pilot.pause()
                assert board.col == 0
                # l moves the selection one lane to the right ...
                await pilot.press("l")
                await pilot.pause()
                assert board.col == 1
                # ... and h moves it back.
                await pilot.press("h")
                await pilot.pause()
                assert board.col == 0

        _run(body())
        # No status was changed - h/l only navigate, never move a card.
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_alt_view_cursor_moves_selection(self, ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView, ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                list_view = app.query_one(ListView)
                first = list_view.selected_id()
                assert first == "T-001"
                await pilot.press("j")
                await pilot.pause()
                assert list_view.selected_id() == "T-002"
                assert list_view.selected_id() != first
                await pilot.press("k")
                await pilot.pause()
                assert list_view.selected_id() == "T-001"
                await pilot.press("v")  # kanban (both open tasks share a column)
                await pilot.pause()
                board = app.query_one(KanbanView)
                top = board.selected_id()
                assert top == "T-001"
                await pilot.press("j")
                await pilot.pause()
                assert board.selected_id() == "T-002"
                assert board.selected_id() != top

        _run(body())

    def test_shift_arrows_jump_to_edges_in_list_and_kanban(self, ctx):
        """Shift+Down / Shift+Up jump to the last / first entry (Pilot)."""
        from doxtr_doto.cli.tui.widgets import KanbanView, ListView, TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Table layout: Shift+Down -> last row, Shift+Up -> first row.
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("shift+down")
                await pilot.pause()
                assert table.selected_id() == "T-002"
                await pilot.press("shift+up")
                await pilot.pause()
                assert table.selected_id() == "T-001"
                # List layout.
                await pilot.press("v")  # list
                await pilot.pause()
                list_view = app.query_one(ListView)
                assert list_view.selected_id() == "T-001"
                await pilot.press("shift+down")
                await pilot.pause()
                assert list_view.selected_id() == "T-002"
                await pilot.press("shift+up")
                await pilot.pause()
                assert list_view.selected_id() == "T-001"
                # Kanban layout (both open tasks share one lane).
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.selected_id() == "T-001"
                await pilot.press("shift+down")
                await pilot.pause()
                assert board.selected_id() == "T-002"
                await pilot.press("shift+up")
                await pilot.pause()
                assert board.selected_id() == "T-001"

        _run(body())

    def test_shift_arrows_jump_to_edges_in_calendar_and_time(self, ctx, store_file):
        """Shift+Down / Shift+Up jump to the last / first entry (calendar/time).

        Companion to
        :meth:`test_shift_arrows_jump_to_edges_in_list_and_kanban`: it exercises
        the ``shift+up`` / ``shift+down`` key-press path end-to-end in the
        remaining two layouts (calendar and time) so the binding wiring that
        routes those presses to
        :meth:`~doxtr_doto.cli.tui.widgets.AltLayoutView.move_cursor_to_edge`
        is covered while each of those views holds focus. Each view exposes its
        cursor differently, so the assertions follow each view's own contract:
        the calendar grid snaps the selected day to the first / last day of the
        visible month, and the time view's day cursor snaps to the newest /
        oldest worked day.
        """
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView, TimeView

        # The calendar grid buckets by due date; give T-001 a due date so the
        # month is deterministic. The time view reads the *global* work clock,
        # so seed three worked days (newest first after rebuild) directly.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        state = ctx.global_store.load()
        state.work_clock.worklogs = [
            {
                "started_at": "2099-01-10T09:00:00+00:00",
                "stopped_at": "2099-01-10T10:00:00+00:00",
            },
            {
                "started_at": "2099-01-11T09:00:00+00:00",
                "stopped_at": "2099-01-11T10:00:00+00:00",
            },
            {
                "started_at": "2099-01-12T09:00:00+00:00",
                "stopped_at": "2099-01-12T10:00:00+00:00",
            },
        ]
        ctx.global_store.save(state)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Calendar layout: in the grid region Shift+Down / Shift+Up
                # snap the selected day to the last / first day of the month.
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-15"
                calendar.rebuild(app._tasks, today=date(2099, 1, 15))
                assert calendar.focus_region == CalendarView.REGION_GRID
                await pilot.press("shift+down")
                await pilot.pause()
                assert calendar.selected == "2099-01-31"
                await pilot.press("shift+up")
                await pilot.pause()
                assert calendar.selected == "2099-01-01"
                # Time layout: the day cursor jumps to the last (oldest) day on
                # Shift+Down and back to the first (newest) day on Shift+Up.
                await pilot.press("v")  # calendar -> time
                await pilot.pause()
                time_view = app.query_one(TimeView)
                assert time_view.selected_day() == date(2099, 1, 12)
                await pilot.press("shift+down")
                await pilot.pause()
                assert time_view.selected_day() == date(2099, 1, 10)
                await pilot.press("shift+up")
                await pilot.pause()
                assert time_view.selected_day() == date(2099, 1, 12)

        _run(body())

    def test_shift_arrows_jump_to_edges_in_current_kanban_lane(
        self, multi_lane_ctx, multi_lane_store_file
    ):
        """Shift+Down / Shift+Up jump within the *now-current* kanban lane.

        The core kanban requirement, exercised through the real key-press path
        rather than a direct ``move_column`` / ``move_cursor_to_edge`` call:
        with tasks in two lanes (``open`` and ``in-progress``), switch lanes
        with ``l``, then Shift+Down lands on the *last* card of the
        now-current lane and Shift+Up on its *first* card - the jump is
        relative to the lane the cursor is in, and no card moves between lanes
        (that is ``Tab`` / ``Shift+Tab``, not Shift+Up/Down).
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(multi_lane_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                # Lane 0 (open) holds T-001, T-002; lane 1 (in-progress) holds
                # T-003, T-004.
                assert board.col == 0
                assert board.selected_id() == "T-001"
                # Move to the second lane (in-progress).
                await pilot.press("l")
                await pilot.pause()
                assert board.col == 1
                assert board.selected_id() == "T-003"
                # Shift+Down lands on the last card of the now-current lane ...
                await pilot.press("shift+down")
                await pilot.pause()
                assert board.col == 1
                assert board.selected_id() == "T-004"
                # ... and Shift+Up on its first card. The lane never changes.
                await pilot.press("shift+up")
                await pilot.pause()
                assert board.col == 1
                assert board.selected_id() == "T-003"

        _run(body())
        # No card moved between lanes - Shift+Up/Down only move the cursor.
        tasks = _load(multi_lane_store_file)["tasks"]
        assert tasks["T-001"]["status"] == "open"
        assert tasks["T-002"]["status"] == "open"
        assert tasks["T-003"]["status"] == "in-progress"
        assert tasks["T-004"]["status"] == "in-progress"

    def test_kanban_tab_moves_card_status_via_actions(self, ctx, store_file):
        """Feature A: Tab moves the selected kanban card to the next status lane."""
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                # Cursor starts on T-001 (open). Tab moves it -> in-progress.
                await pilot.press("tab")
                await pilot.pause()

        _run(body())
        # The status change was written through actions.update_task.
        assert _load(store_file)["tasks"]["T-001"]["status"] == "in-progress"

    def test_calendar_selects_day_and_buckets_undated(self, ctx, store_file):
        from doxtr_doto.cli.tui.widgets import CalendarView

        # Give T-001 a due date; T-002 stays undated.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                # The dated task is bucketed by its ISO due date.
                assert [t["id"] for t in calendar.buckets["2099-01-15"]] == ["T-001"]
                # The undated task is in the no-due bucket.
                undated = [t["id"] for t in calendar.buckets[CalendarView.NO_DUE_KEY]]
                assert "T-002" in undated
                # Selecting the due day surfaces that day's task.
                calendar.selected = "2099-01-15"
                assert [t["id"] for t in calendar.selected_tasks()] == ["T-001"]

        _run(body())

    def test_calendar_tab_into_due_region_sets_selection(self, ctx, store_file):
        """Feature A: Tab into the Due region makes selected_id the due task."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        # Two tasks due on the selected day; one undated.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        actions.update_task(ctx, "T-002", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-15"
                calendar.rebuild(app._tasks, today=date(2099, 1, 15))
                # Grid region: selected_id is the first due task.
                assert calendar.focus_region == CalendarView.REGION_GRID
                assert app._current_selected_id() == "T-001"
                # Tab into the Due region: selected_id tracks the cursor.
                await pilot.press("tab")
                await pilot.pause()
                assert calendar.focus_region == CalendarView.REGION_DUE
                assert app._current_selected_id() == "T-001"
                # j moves the Due cursor to the second due task.
                await pilot.press("j")
                await pilot.pause()
                assert calendar.region_cursor == 1
                assert app._current_selected_id() == "T-002"

        _run(body())

    def test_calendar_no_due_region_enter_and_edit(self, ctx, store_file):
        """Feature B: focus the No-due list; Enter and e act on the cursor task."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        # T-001 dated, T-002 undated -> the no-due bucket.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-15"
                calendar.rebuild(app._tasks, today=date(2099, 1, 15))
                # Tab grid -> Due -> No-due.
                await pilot.press("tab")
                await pilot.press("tab")
                await pilot.pause()
                assert calendar.focus_region == CalendarView.REGION_NO_DUE
                assert app._current_selected_id() == "T-002"
                # Enter opens the card viewer for the highlighted no-due task.
                await pilot.press("enter")
                await pilot.pause()
                assert app.screen_stack[-1].__class__.__name__ == "CardViewerScreen"
                await pilot.press("escape")
                await pilot.pause()
                # e opens the edit dialog for the same task.
                await pilot.press("e", "e")
                await pilot.pause()
                assert app.screen_stack[-1].__class__.__name__ == "EditTaskScreen"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_calendar_assign_due_moves_no_due_task(self, ctx, store_file):
        """Feature C: A assigns the selected day to the highlighted no-due task."""
        from datetime import date

        from doxtr_doto.cli.tui.widgets import CalendarView

        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})  # T-002 undated
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-20"
                calendar.rebuild(app._tasks, today=date(2099, 1, 20))
                # Focus the No-due region (grid -> Due -> No-due).
                await pilot.press("tab")
                await pilot.press("tab")
                await pilot.pause()
                assert calendar.focus_region == CalendarView.REGION_NO_DUE
                assert calendar.assign_task_id() == "T-002"
                # Assign the selected day (2099-01-20) to the undated task.
                await pilot.press("A")
                await pilot.pause()
                # The task now appears under that day's Due bucket and leaves
                # the no-due bucket.
                assert "T-002" in [t["id"] for t in calendar.buckets["2099-01-20"]]
                assert "T-002" not in [
                    t["id"] for t in calendar.buckets.get(CalendarView.NO_DUE_KEY, [])
                ]

        _run(body())
        # The assignment was persisted through actions.update_task.
        assert _load(store_file)["tasks"]["T-002"]["due"] == "2099-01-20"

    def test_calendar_assign_due_noop_without_no_due_cursor(self, ctx, store_file):
        """Feature C: A is a documented no-op when no no-due task is highlighted."""
        from doxtr_doto.cli.tui.widgets import CalendarView

        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                # Grid region: no no-due task highlighted -> no-op.
                assert calendar.focus_region == CalendarView.REGION_GRID
                await pilot.press("A")
                await pilot.pause()

        _run(body())
        # T-002 stays undated: the no-op did not write a due date.
        assert "due" not in _load(store_file)["tasks"]["T-002"]

    def test_calendar_assign_due_error_branch_keeps_no_due_task(self, ctx, store_file, monkeypatch):
        """Fix #9a: a failed update_task notifies an error and keeps the task."""
        from datetime import date

        from doxtr_doto.cli.tui import actions as tui_actions
        from doxtr_doto.cli.tui.widgets import CalendarView

        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})  # T-002 undated
        app = self._app(ctx)
        # Force the mutation to fail so the error branch runs.
        monkeypatch.setattr(tui_actions, "update_task", lambda *a, **k: False)
        notifications: list[tuple[str, str]] = []
        app.notify = lambda message, **kw: notifications.append(  # type: ignore[method-assign]
            (message, kw.get("severity", "information"))
        )

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-20"
                calendar.rebuild(app._tasks, today=date(2099, 1, 20))
                await pilot.press("tab")
                await pilot.press("tab")
                await pilot.pause()
                assert calendar.focus_region == CalendarView.REGION_NO_DUE
                assert calendar.assign_task_id() == "T-002"
                await pilot.press("A")
                await pilot.pause()
                # The error notify path was taken.
                assert any(sev == "error" for _, sev in notifications)
                # The task stayed in the no-due bucket (nothing moved).
                assert "T-002" in [
                    t["id"] for t in calendar.buckets.get(CalendarView.NO_DUE_KEY, [])
                ]

        _run(body())
        # No due date was persisted (update_task was stubbed to fail).
        assert "due" not in _load(store_file)["tasks"]["T-002"]

    def test_layout_preference_persists(self, ctx):
        from doxtr_doto.enums import TuiLayout

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()

        _run(body())
        # The chosen layout was persisted to global state as the default.
        assert ctx.global_store.load().tui_layout == "kanban"
        assert actions.load_tui_layout(ctx) == TuiLayout.KANBAN

        # A fresh app restores the persisted layout on launch.
        app2 = self._app(ctx)

        async def body2():
            async with app2.run_test() as pilot:
                await pilot.pause()
                assert app2.layout_view == TuiLayout.KANBAN

        _run(body2())

    def test_edit_works_in_list_layout(self, ctx, store_file):
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout
                await pilot.pause()
                await pilot.press("e", "e")  # edit the list-view's selected task
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                app.screen.query_one("#edit-title-input", Input).value = "From list"
                app.screen._submit()
                await pilot.pause()

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["title"] == "From list"

    def test_view_classes_are_overridable(self, ctx, store_file):
        """A child theme can swap each layout view via the *_class seams."""
        from doxtr_doto.cli.tui.app import DotoApp
        from doxtr_doto.cli.tui.widgets import CalendarView, KanbanView, ListView

        # The seams exist and default to the built-in view widgets.
        assert DotoApp.list_view_class is ListView
        assert DotoApp.kanban_view_class is KanbanView
        assert DotoApp.calendar_view_class is CalendarView

        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _ThemedLayoutApp(ctx)
        app.scope = DisplayScope.LOCAL  # current-repo content; GLOBAL default shows nothing

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # The themed app rendered the child-theme view subclasses.
                assert isinstance(app.query_one("#list-view"), _ThemedListView)
                assert isinstance(app.query_one("#kanban-view"), _ThemedKanbanView)
                assert isinstance(app.query_one("#calendar-view"), _ThemedCalendarView)

        _run(body())

    def test_overridden_format_reaches_render(self, ctx):
        """An overridden ``format_*`` classmethod reaches the rendered output.

        Proves the overridability seam is wired through to the screen (not just
        that the subclass instance mounted): the themed list view prefixes each
        line with a sentinel, which must appear in the view's rendered content.
        """
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.widgets import ListView

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _SentinelLayoutApp(ctx)
        app.scope = DisplayScope.LOCAL  # current-repo content; GLOBAL default shows nothing

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout (sentinel-emitting view)
                await pilot.pause()
                view = app.query_one(ListView)
                assert isinstance(view, _SentinelListView)
                # The overridden format_line's sentinel reached the render.
                assert _RENDER_SENTINEL in view.rendered_text()

        _run(body())

    def test_calendar_highlight_flows_through_seam(self, ctx, store_file):
        """The active-region highlight routes through the overridable seam.

        A child theme that overrides ``format_entry`` controls how the
        highlighted task renders: focusing the Due region must make the
        themed calendar's highlight sentinel appear in the rendered output,
        proving the highlight flows through ``format_day_detail`` /
        ``format_entry`` rather than hardcoded markup.
        """
        from datetime import date

        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.widgets import CalendarView

        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _SentinelCalendarApp(ctx)
        app.scope = DisplayScope.LOCAL  # current-repo content; GLOBAL default shows nothing

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-15"
                calendar.rebuild(app._tasks, today=date(2099, 1, 15))
                # Grid region: nothing highlighted, no sentinel.
                assert _CAL_HIGHLIGHT_SENTINEL not in calendar.rendered_text()
                # Tab into the Due region: the highlighted entry's sentinel
                # (from the themed format_entry override) reaches the render.
                await pilot.press("tab")
                await pilot.pause()
                assert calendar.focus_region == CalendarView.REGION_DUE
                assert _CAL_HIGHLIGHT_SENTINEL in calendar.rendered_text()

        _run(body())

    def test_enter_opens_card_viewer_in_list_layout(self, ctx):
        """``Enter`` opens the card viewer popup in the list layout (Feature 3).

        The list layout has no dedicated details pane, so activating the
        highlighted row opens the shared card viewer popup, mirroring the
        kanban layout.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen
        from doxtr_doto.cli.tui.widgets import ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout
                await pilot.pause()
                list_view = app.query_one(ListView)
                selected = list_view.selected_id()
                assert selected == "T-001"
                await pilot.press("enter")
                await pilot.pause()
                # Enter opens the card viewer popup (not the details pane).
                assert isinstance(app.screen, CardViewerScreen)
                task = actions.find_task(ctx, selected)
                assert task is not None
                detail = str(app.screen.query_one("#viewer-detail").render())
                assert task["title"] in detail
                # Enter again closes the popup.
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, CardViewerScreen)

        _run(body())

    def test_details_pane_shows_the_selected_task_id(self, ctx):
        """Regression: the details pane must show the selected task's id.

        The details pane is populated via :meth:`refresh_details`, which used
        to load the raw store task (``JsonTaskStore.get_task``) - a dict with
        no ``id`` key - so :meth:`TaskDetails.format_details` rendered an empty
        ``[bold][/bold]`` id. Resolving against the gathered task set (which
        carries the display id) fixes it, so the id is visible in the pane.
        """
        from doxtr_doto.cli.tui.widgets import TaskDetails

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                details = app.query_one(TaskDetails)
                content = str(details.content)
                # The default-selected task (T-001) renders its id, not an
                # empty bold span.
                assert "T-001" in content
                assert "[bold][/bold]" not in content

        _run(body())

    def test_arrow_keys_navigate_table_layout(self, ctx):
        """Down/Up arrows move the cursor in the default table layout.

        Bug 1: arrow keys must mirror j/k on every layout. The table layout's
        DataTable has focus, so the arrows drive the same cursor move j/k do.
        """
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("down")
                await pilot.pause()
                assert table.selected_id() == "T-002"
                await pilot.press("up")
                await pilot.pause()
                assert table.selected_id() == "T-001"

        _run(body())

    def test_arrow_keys_navigate_list_layout(self, ctx):
        """Down/Up arrows move the cursor in the list layout (Bug 1)."""
        from doxtr_doto.cli.tui.widgets import ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout
                await pilot.pause()
                list_view = app.query_one(ListView)
                assert list_view.selected_id() == "T-001"
                await pilot.press("down")
                await pilot.pause()
                assert list_view.selected_id() == "T-002"
                await pilot.press("up")
                await pilot.pause()
                assert list_view.selected_id() == "T-001"

        _run(body())

    def test_arrow_keys_navigate_kanban_layout(self, ctx):
        """Down/Up arrows move the cursor within a kanban column (Bug 1)."""
        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban (both open tasks share a column)
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.selected_id() == "T-001"
                await pilot.press("down")
                await pilot.pause()
                assert board.selected_id() == "T-002"
                await pilot.press("up")
                await pilot.pause()
                assert board.selected_id() == "T-001"

        _run(body())

    def test_left_right_arrows_navigate_kanban_lanes(self, ctx, store_file):
        """Feature A: Left/Right arrows navigate kanban lanes (mirror h/l).

        Arrows move the *selection* across swim lanes without changing any
        task's status - the card-move is now on Tab/Shift+Tab.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.col == 0
                await pilot.press("right")  # select next lane
                await pilot.pause()
                assert board.col == 1
                await pilot.press("left")  # select previous lane
                await pilot.pause()
                assert board.col == 0

        _run(body())
        # Navigation never changed any status.
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_left_right_arrows_move_calendar_day(self, ctx):
        """Left/Right arrows mirror h/l: move the selected calendar day."""
        from datetime import date, timedelta

        from doxtr_doto.cli.tui.widgets import CalendarView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                start = date.fromisoformat(calendar.selected)
                await pilot.press("right")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start + timedelta(days=1)
                await pilot.press("left")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start

        _run(body())

    def test_arrows_harmless_in_table_layout_left_right(self, ctx, store_file):
        """Left/Right arrows are a no-op in the table layout (like h/l)."""
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("left")
                await pilot.press("right")
                await pilot.pause()
                # Still on the same row; nothing mutated.
                assert table.selected_id() == "T-001"

        _run(body())
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_enter_reveals_details_in_table_layout(self, ctx):
        """``Enter`` reveals the selected row's details in the table layout.

        The table is the default 3-pane layout with its own details pane, so
        (unlike the list/kanban/calendar layouts) Enter reveals details inline
        and does *not* open the card viewer popup. The table's DataTable
        consumes Enter via RowSelected, which the app handles to focus details.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen
        from doxtr_doto.cli.tui.widgets import TaskDetails

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                selected = app._current_selected_id()
                assert selected == "T-001"
                await pilot.press("enter")
                await pilot.pause()
                # Enter reveals details inline; it must not open the popup.
                assert not isinstance(app.screen, CardViewerScreen)
                details = app.query_one(TaskDetails)
                assert app.focused is details
                task = actions.find_task(ctx, selected)
                assert task is not None
                assert task["title"] in str(details.render())

        _run(body())

    def test_enter_opens_card_viewer_in_kanban_layout(self, ctx):
        """``Enter`` opens the card viewer popup in the kanban layout (Feature 3)."""
        from doxtr_doto.cli.tui.app import CardViewerScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                selected = app._current_selected_id()
                assert selected == "T-001"
                await pilot.press("enter")
                await pilot.pause()
                # Enter opens the card viewer popup (not the details pane).
                assert isinstance(app.screen, CardViewerScreen)
                task = actions.find_task(ctx, selected)
                assert task is not None
                detail = str(app.screen.query_one("#viewer-detail").render())
                assert task["title"] in detail
                # Enter again closes the popup.
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, CardViewerScreen)

        _run(body())

    def test_card_viewer_markdown_headers_contrast_on_dark_theme(self, ctx):
        """Markdown headers in the viewer body stay readable + distinct (dark).

        Regression guard for the theming bug where the task body's Markdown
        headers rendered from the stock ``$markdown-h*-color`` tokens, which on
        ``ansi-dark`` resolved H3 to the dark navy ``ansi_blue`` (ansi index 4)
        on a dark surface - effectively invisible - and on several themes
        collapsed H1/H2/H3 to a single accent colour. The ``#viewer-md`` CSS
        now colours the headers from the contrast-tuned ``$text-*`` theme
        tokens (``$text-accent`` / ``$text-secondary`` / ``$text-error`` for
        H1/H2/H3, ``$text`` for h4-h6).

        The assertions are theme-token-robust: rather than pinning an RGB that
        a future token tweak would break, they assert the invariant that broke
        before - no header uses the invisible dark navy ``ansi_blue`` and the
        three top levels stay mutually distinct - so the exact regression
        (invisible dark-blue H3 on a dark theme) can never silently return.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen, DotoApp

        try:
            from textual.widgets._markdown import (
                MarkdownH1,
                MarkdownH2,
                MarkdownH3,
                MarkdownHeader,
            )
        except ImportError:  # pragma: no cover - older/newer textual layout
            pytest.skip("textual MarkdownHeader internals unavailable")

        body_md = (
            "# H1 heading\n"
            "## H2 heading\n"
            "### H3 heading\n"
            "#### H4 heading\n\n"
            "Some **bold** text and `inline code`.\n\n"
            "- item one\n"
            "- item two\n"
        )
        task = {
            "id": "T-001",
            "title": "Headered",
            "status": "open",
            "priority": "high",
            "body": body_md,
        }

        app = DotoApp(ctx)

        async def body():
            async with app.run_test(size=(80, 30)) as pilot:
                await pilot.pause()
                # The ansi-dark theme is the exact case that broke before.
                app.theme = "ansi-dark"
                await pilot.pause()
                screen = CardViewerScreen(task)
                await app.push_screen(screen)
                await pilot.pause()

                headers = list(screen.query(MarkdownHeader))
                # H1..H4 are all present (so h4-h6 styling is exercised too).
                assert len(headers) >= 4

                for h in headers:
                    color = h.styles.color
                    assert color is not None
                    # The regression: H3 used ``ansi_blue`` (ansi index 4), a
                    # dark navy, invisible on a dark surface. No viewer header
                    # may use it.
                    assert getattr(color, "ansi", None) != 4, (
                        f"{type(h).__name__} uses the invisible dark navy "
                        f"ansi_blue (ansi=4): {color}"
                    )

                # The three top header levels must stay mutually distinct so
                # they no longer collapse into one indistinguishable accent.
                top = {}
                for h in headers:
                    if isinstance(h, MarkdownH1):
                        top["h1"] = h.styles.color
                    elif isinstance(h, MarkdownH2):
                        top["h2"] = h.styles.color
                    elif isinstance(h, MarkdownH3):
                        top["h3"] = h.styles.color
                assert {"h1", "h2", "h3"} <= set(top)
                keys = [(c.r, c.g, c.b) for c in top.values()]
                assert len(set(keys)) == len(keys), f"H1/H2/H3 colours collapsed together: {top}"

        _run(body())

    def test_card_viewer_markdown_headers_contrast_rgb_theme(self, ctx):
        """On an RGB theme, viewer Markdown headers clear a contrast threshold.

        Complements the ansi-dark guard by asserting *measurable* WCAG-style
        contrast on a concrete-RGB dark theme (``textual-dark``), where the
        resolved header colours have real RGB values (unlike the ansi palette,
        whose nominal RGB is terminal-governed). Each of H1/H2/H3 must contrast
        clearly against the ``#viewer-md`` background, catching any future
        token change that would push a header toward the surface colour.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen, DotoApp

        try:
            from textual.widgets._markdown import MarkdownHeader
        except ImportError:  # pragma: no cover - older/newer textual layout
            pytest.skip("textual MarkdownHeader internals unavailable")

        def luminance(color):
            def chan(v):
                v /= 255.0
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

            return 0.2126 * chan(color.r) + 0.7152 * chan(color.g) + 0.0722 * chan(color.b)

        def contrast(fg, bg):
            lo, hi = sorted((luminance(fg), luminance(bg)))
            return (hi + 0.05) / (lo + 0.05)

        body_md = "# H1\n## H2\n### H3\n#### H4\n"
        task = {
            "id": "T-001",
            "title": "Headered",
            "status": "open",
            "priority": "high",
            "body": body_md,
        }

        app = DotoApp(ctx)

        async def body():
            async with app.run_test(size=(80, 30)) as pilot:
                await pilot.pause()
                app.theme = "textual-dark"
                await pilot.pause()
                screen = CardViewerScreen(task)
                await app.push_screen(screen)
                await pilot.pause()

                md = screen.query_one("#viewer-md")
                bg = md.background_colors[1]
                for h in screen.query(MarkdownHeader):
                    color = h.styles.color
                    assert color is not None
                    if getattr(color, "auto", False):
                        resolved = bg.get_contrast_text(color.a if color.a is not None else 1.0)
                    else:
                        resolved = (bg + color).clamped
                    ratio = contrast(resolved, bg)
                    # 3.0 is the WCAG AA large-text / UI-component threshold;
                    # the pre-fix ansi-dark H3 scored ~1.3.
                    assert ratio >= 3.0, (
                        f"{type(h).__name__} contrast {ratio:.2f} too low (color={color}, bg={bg})"
                    )

        _run(body())

    def test_card_viewer_build_detail_lines_shape(self):
        """The card viewer's detail assembly carries the full task fields.

        Feature 3: ``build_detail_lines`` is the pure, testable method (like
        :meth:`EditTaskScreen.build_fields`) that mirrors the
        ``doto list -f cards`` field shape, so assert it emits every field.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "A title",
            "assignee": "alice",
            "priority": "high",
            "status": "in-progress",
            "due": "2099-01-15",
            "tags": ["x", "y"],
            "depends_on": ["T-0"],
            "_series_info": {
                "series_id": "S-1",
                "pattern": "weekly",
                "until": "2099-12-31",
            },
            "created": "2024-01-01",
            "updated": "2024-02-02",
            "body": "the long body text",
        }
        plain = Text.from_markup("\n".join(CardViewerScreen.build_detail_lines(task))).plain
        for expected in (
            "T-1",
            "A title",
            "Assignee:",
            "alice",
            "Priority:",
            "high",
            "Status:",
            "in-progress",
            "Due:",
            "2099-01-15",
            "Tags:",
            "x, y",
            "Depends on:",
            "T-0",
            "Series:",
            "S-1",
            "weekly",
            "Created:",
            "2024-01-01",
            "Updated:",
            "2024-02-02",
            "the long body text",
        ):
            assert expected in plain, expected

    def test_card_viewer_detail_lines_share_single_source_with_cli(self):
        """The viewer derives its field list from the shared CLI builder.

        rev-ext/rev-maint: ``build_detail_lines`` must not be a second
        hand-maintained copy of the ``doto list -f cards`` field set. It
        delegates to :func:`doxtr_doto.cli.output.build_task_detail_lines`,
        the single source both the CLI card and the TUI viewer consume, so a
        new/changed detail field shows up in both without editing two places.
        """
        from doxtr_doto.cli.output import build_task_detail_lines
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "A title",
            "assignee": "alice",
            "priority": "high",
            "status": "in-progress",
            "due": "2099-01-15",
            "tags": ["x", "y"],
            "body": "body",
        }
        assert CardViewerScreen.build_detail_lines(task) == build_task_detail_lines(task)

    def test_card_viewer_styles_overdue_due_like_the_cli(self):
        """An overdue, non-done due date is styled red bold, matching the CLI.

        rev-maint/rev-smell: the viewer previously rendered the due date plain,
        dropping the overdue cue the CLI card shows. The shared builder keeps
        them in lockstep.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen

        overdue = {"id": "T-1", "title": "t", "status": "open", "due": "2000-01-01"}
        lines = "\n".join(CardViewerScreen.build_detail_lines(overdue))
        assert "[red bold]2000-01-01[/red bold]" in lines
        # A done task's past due date is not flagged overdue.
        done = {"id": "T-1", "title": "t", "status": "done", "due": "2000-01-01"}
        assert "red bold" not in "\n".join(CardViewerScreen.build_detail_lines(done))

    def test_card_viewer_escapes_markup_in_free_text(self):
        """Free-text values with brackets are escaped, not parsed as markup.

        rev-smell: a title like ``"[WIP] fix"`` must render literally rather
        than being interpreted as a Textual style tag (which could break
        rendering or raise MarkupError).
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-1", "title": "[WIP] fix", "status": "open", "body": "see [done]"}
        rendered = "\n".join(CardViewerScreen.build_detail_lines(task))
        # The literal bracketed text survives when the markup is parsed back.
        plain = Text.from_markup(rendered).plain
        assert "[WIP] fix" in plain
        assert "see [done]" in plain

    def test_card_viewer_detail_omits_missing_optional_fields(self):
        """Optional fields the task lacks are not emitted (matches the CLI card)."""
        from rich.text import Text

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-1", "title": "Bare", "status": "open"}
        plain = Text.from_markup("\n".join(CardViewerScreen.build_detail_lines(task))).plain
        # Priority/Status always render; the rest are conditional on presence.
        assert "Status:" in plain
        assert "Assignee:" not in plain
        assert "Tags:" not in plain
        assert "Depends on:" not in plain
        assert "Series:" not in plain

    def test_card_viewer_field_lines_exclude_body(self):
        """``build_field_lines`` returns the fields without the body.

        The body is rendered separately as Markdown, so the field (style-
        markup) lines must stop before the body and its blank separator while
        still carrying every non-body field.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "A title",
            "assignee": "alice",
            "status": "open",
            "body": "# Heading\n\nbody text",
        }
        fields = CardViewerScreen.build_field_lines(task)
        plain = Text.from_markup("\n".join(fields)).plain
        assert "A title" in plain
        assert "Assignee:" in plain
        # The body and its trailing blank separator are not in the field lines.
        assert "body text" not in plain
        assert "# Heading" not in plain
        # The field lines are exactly the detail lines minus the body pair.
        assert fields == CardViewerScreen.build_detail_lines(task)[:-2]

    def test_card_viewer_field_lines_without_body_equal_detail_lines(self):
        """With no body the field lines are the full detail lines unchanged."""
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-1", "title": "Bare", "status": "open"}
        assert CardViewerScreen.build_field_lines(task) == CardViewerScreen.build_detail_lines(task)

    def test_card_viewer_body_markdown_is_raw_not_escaped(self):
        """``build_body_markdown`` returns the body verbatim for Markdown.

        Unlike the style-markup field lines, the body is fed to the Markdown
        widget unescaped so its Markdown markup renders. No body yields
        ``None`` so :meth:`compose` adds no empty Markdown region.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-1", "title": "t", "status": "open", "body": "# H\n\n**bold**"}
        assert CardViewerScreen.build_body_markdown(task) == "# H\n\n**bold**"
        no_body = {"id": "T-1", "title": "t", "status": "open"}
        assert CardViewerScreen.build_body_markdown(no_body) is None
        empty_body = {"id": "T-1", "title": "t", "status": "open", "body": ""}
        assert CardViewerScreen.build_body_markdown(empty_body) is None

    def test_card_viewer_default_user_defaults_empty(self):
        """The viewer's ``default_user`` defaults to empty when constructed bare."""
        from doxtr_doto.cli.tui.app import CardViewerScreen

        screen = CardViewerScreen({"id": "T-1", "title": "t", "status": "open"})
        assert screen.default_user == ""
        screen2 = CardViewerScreen({"id": "T-1", "title": "t", "status": "open"}, "alice")
        assert screen2.default_user == "alice"

    def test_card_viewer_extra_lines_raci_suppresses_default_user(self):
        """RACI roles that are only the default user are suppressed in the popup.

        Feature: the card viewer shows RACI info only for roles whose names
        *differ* from the configured default user, so a role assigned to the
        boring default (the person running the tool) does not clutter the
        popup while a genuinely different assignment is surfaced.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "t",
            "status": "open",
            "raci": {"responsible": ["alice"], "consulted": ["bob"]},
        }
        screen = CardViewerScreen(task, "alice")
        plain = Text.from_markup("\n".join(screen.build_extra_field_lines(task))).plain
        # alice (the default user) is the sole responsible -> suppressed.
        assert "Responsible" not in plain
        # bob (consulted) differs -> shown.
        assert "Consulted: bob" in plain

    def test_card_viewer_extra_lines_empty_without_raci_or_worklogs(self):
        """No RACI and no worklogs -> no extra popup lines."""
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-1", "title": "t", "status": "open"}
        screen = CardViewerScreen(task, "alice")
        assert screen.build_extra_field_lines(task) == []

    def test_card_viewer_extra_lines_time_spent(self):
        """A task with tracked time shows a ``Time spent`` line in the popup."""
        from rich.text import Text

        from doxtr_doto.cli.session import format_duration
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "t",
            "status": "open",
            "worklogs": [
                {
                    "started_at": "2026-06-01T09:00:00+00:00",
                    "stopped_at": "2026-06-01T10:00:00+00:00",
                }
            ],
        }
        screen = CardViewerScreen(task, "")
        plain = Text.from_markup("\n".join(screen.build_extra_field_lines(task))).plain
        assert "Time spent:" in plain
        assert format_duration(3600) in plain

    def test_card_viewer_extra_lines_omit_zero_time(self):
        """Worklogs that sum to zero elapsed produce no ``Time spent`` line."""
        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-1",
            "title": "t",
            "status": "open",
            "worklogs": [
                {
                    "started_at": "2026-06-01T09:00:00+00:00",
                    "stopped_at": "2026-06-01T09:00:00+00:00",
                }
            ],
        }
        screen = CardViewerScreen(task, "")
        assert screen.build_extra_field_lines(task) == []

    def test_card_viewer_renders_markdown_body_full_height(self, ctx):
        """The body renders in a full-height Markdown widget inside the scroll.

        Asserts (a) the body is a :class:`~textual.widgets.Markdown` widget
        (markup rendered, not a plain Label), (b) it lives in the
        ``height: 1fr`` ``#viewer-body`` scroll so it fills to the modal's
        bottom, and (c) the field lines still render in ``#viewer-detail``.
        """
        from textual.widgets import Markdown, Static

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-9",
            "title": "Markdown task",
            "status": "open",
            "body": "# Heading\n\n- item one\n- item two\n\n**bold** and `code`",
        }
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(CardViewerScreen(task))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                # (c) Field lines render in the Static detail region.
                detail = screen.query_one("#viewer-detail", Static)
                assert "Markdown task" in str(detail.render())
                # (a) The body is a Markdown widget (markup rendering).
                md = screen.query_one("#viewer-md", Markdown)
                # (b) It lives inside the full-height ``#viewer-body`` scroll.
                from textual.containers import VerticalScroll

                scroll = screen.query_one("#viewer-body", VerticalScroll)
                assert md in list(scroll.walk_children(Markdown))
                assert scroll.styles.height is not None
                assert scroll.styles.height.value == 1
                assert scroll.styles.height.unit.name == "FRACTION"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_field_region_wraps_long_values(self, ctx):
        """Long title/assignee wrap in ``#viewer-detail`` (not clipped).

        The user's hard requirement is "properly wrapped" text. This asserts
        the *full* long title and assignee are present in the rendered detail
        region (nothing truncated/ellipsized) AND that the live Static spans
        multiple visual rows at the modal width, mirroring the kanban
        clip-tests' ``cell_len``/line-count style but verifying *wrapping*
        rather than clipping.
        """
        from rich.text import Text
        from textual.widgets import Static

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = _long_task()
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                app.push_screen(CardViewerScreen(task))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                detail = screen.query_one("#viewer-detail", Static)
                plain = _plain(str(detail.render()))
                # The full long values are present, not truncated/ellipsized.
                assert LONG_TITLE in plain
                assert LONG_ASSIGNEE in plain
                assert "\u2026" not in plain  # no ellipsis -> not clipped
                # The live widget wraps across multiple visual rows: its laid
                # out height exceeds the number of source field lines (a
                # clipped single-line-per-field region could not), and every
                # visual row fits the widget width (no sideways overflow).
                width = detail.size.width
                height = detail.size.height
                assert width > 0
                field_lines = CardViewerScreen.build_field_lines(task)
                assert height > len(field_lines)
                for y in range(height):
                    row = detail.render_line(y)
                    assert Text(row.text).cell_len <= width
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_markdown_body_receives_long_source_verbatim(self, ctx):
        """The Markdown body widget gets the full long body source verbatim.

        Markdown wrapping is framework-owned, so rather than assert the
        rendered row layout we pin that the full ``LONG_BODY`` reaches the
        widget's ``source`` unchanged (so the framework can wrap it), which is
        the input precondition for "properly wrapped" body prose.
        """
        from textual.widgets import Markdown

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = _long_task()
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(CardViewerScreen(task))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                md = screen.query_one("#viewer-md", Markdown)
                assert md.source == LONG_BODY
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_omits_markdown_region_without_body(self, ctx):
        """No body means no Markdown region is mounted (no empty widget)."""
        from textual.widgets import Markdown

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {"id": "T-9", "title": "No body", "status": "open"}
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(CardViewerScreen(task))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                assert len(screen.query("#viewer-md")) == 0
                assert len(screen.query(Markdown)) == 0
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_renders_extra_fields_in_detail_region(self, ctx):
        """The RACI-differing and time-spent lines render in ``#viewer-detail``.

        The popup-only extra fields (:meth:`build_extra_field_lines`) are
        rendered into the same soft-wrapping Static as the shared field lines.
        """
        from textual.widgets import Static

        from doxtr_doto.cli.tui.app import CardViewerScreen

        task = {
            "id": "T-9",
            "title": "t",
            "status": "open",
            "raci": {"consulted": ["bob"]},
            "worklogs": [
                {
                    "started_at": "2026-06-01T09:00:00+00:00",
                    "stopped_at": "2026-06-01T10:00:00+00:00",
                }
            ],
        }
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(CardViewerScreen(task, "alice"))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                detail = screen.query_one("#viewer-detail", Static)
                rendered = _plain(str(detail.render()))
                assert "Consulted: bob" in rendered
                assert "Time spent:" in rendered
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_open_card_viewer_threads_default_user(self, ctx):
        """``_open_card_viewer`` passes the resolved default user to the screen.

        The default user is ``config.user`` falling back to
        ``config.default_assignee``; the viewer uses it to suppress RACI roles
        assigned only to that person.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen

        ctx.config.user = ""
        ctx.config.default_assignee = "zoe"
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app._open_card_viewer("T-001")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardViewerScreen)
                # user is empty -> falls back to default_assignee.
                assert screen.default_user == "zoe"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_body_rendering_is_overridable(self, ctx):
        """A child theme can swap the body rendering via its override seams.

        Overriding :attr:`CardViewerScreen.markdown_class` (and the body
        source via :meth:`build_body_markdown`) must flow through to the
        mounted body widget, proving a theme can replace the rendering.
        """
        from textual.widgets import Markdown

        from doxtr_doto.cli.tui.app import CardViewerScreen

        class _ThemedMarkdown(Markdown):
            """Stand-in for a child theme's custom Markdown body widget."""

        class _ThemedBodyViewer(CardViewerScreen):
            markdown_class = _ThemedMarkdown

            @classmethod
            def build_body_markdown(cls, task):
                src = super().build_body_markdown(task)
                return None if src is None else f"{src}\n\nTHEME-APPENDED"

        task = {"id": "T-9", "title": "t", "status": "open", "body": "# Base body"}
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(_ThemedBodyViewer(task))
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, _ThemedBodyViewer)
                md = screen.query_one("#viewer-md", Markdown)
                # The themed Markdown subclass was used...
                assert isinstance(md, _ThemedMarkdown)
                # ...and the overridden body source reached the widget.
                assert "THEME-APPENDED" in md.source
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_e_opens_edit_dialog(self, ctx):
        """``e`` in the card viewer closes it and opens the edit dialog (Feature 4)."""
        from doxtr_doto.cli.tui.app import CardViewerScreen, EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                assert app._current_selected_id() == "T-001"
                await pilot.press("enter")  # open card viewer
                await pilot.pause()
                assert isinstance(app.screen, CardViewerScreen)
                await pilot.press("e")  # close viewer, open edit
                await pilot.pause()
                # The viewer closed and the existing edit dialog opened for
                # the same task (reusing the edit flow, not a new one).
                assert isinstance(app.screen, EditTaskScreen)
                assert app.screen.edit_task["id"] == "T-001"
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_card_viewer_edit_updates_store_and_refreshes_board(self, ctx):
        """Editing from the viewer writes via update_task and refreshes the board."""
        from textual.widgets import Input

        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                await pilot.press("enter")  # viewer
                await pilot.pause()
                await pilot.press("e")  # -> edit
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)
                title = app.screen.query_one("#edit-title-input", Input)
                title.value = "Edited from viewer"
                app.screen._submit()
                await pilot.pause()
                # The store was updated via the reused update_task flow.
                task = actions.find_task(ctx, "T-001")
                assert task is not None
                assert task["title"] == "Edited from viewer"
                # And the board reflects the refreshed task set.
                assert any(
                    t["id"] == "T-001" and t["title"] == "Edited from viewer" for t in app._tasks
                )

        _run(body())

    def test_card_viewer_screen_is_overridable(self, ctx):
        """A child theme can swap the card viewer via card_viewer_screen_class."""
        from doxtr_doto.cli.tui.app import CardViewerScreen, DotoApp

        # The seam exists and defaults to the built-in viewer.
        assert DotoApp.card_viewer_screen_class is CardViewerScreen
        # Suppress the kickstart nudge so Enter opens the viewer directly.
        from doxtr_doto.cli.tui import nudge

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = _ThemedViewerApp(ctx)
        app.scope = DisplayScope.LOCAL  # current-repo content; GLOBAL default shows nothing

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                # The themed app opened the child-theme viewer subclass.
                assert isinstance(app.screen, _ThemedCardViewerScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())

    def test_enter_opens_card_viewer_in_calendar_layout(self, ctx, store_file):
        """``Enter`` opens the card viewer popup in the calendar layout (Feature 3).

        The calendar layout has no dedicated details pane, so activating the
        selected day's first due task opens the shared card viewer popup,
        mirroring the kanban layout.
        """
        from doxtr_doto.cli.tui.app import CardViewerScreen
        from doxtr_doto.cli.tui.widgets import CalendarView

        # Give T-001 a due date so the calendar has a selectable task.
        actions.update_task(ctx, "T-001", {"due": "2099-01-15"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                calendar.selected = "2099-01-15"
                calendar.rebuild(app._tasks)
                await pilot.pause()
                selected = app._current_selected_id()
                assert selected == "T-001"
                await pilot.press("enter")
                await pilot.pause()
                # Enter opens the card viewer popup (not the details pane).
                assert isinstance(app.screen, CardViewerScreen)
                task = actions.find_task(ctx, selected)
                assert task is not None
                detail = str(app.screen.query_one("#viewer-detail").render())
                assert task["title"] in detail
                # Enter again closes the popup.
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, CardViewerScreen)

        _run(body())

    def test_enter_noop_when_nothing_selectable(self, empty_ctx):
        """``Enter`` is a harmless no-op when the store has no tasks."""
        app = self._app(empty_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout, empty store
                await pilot.pause()
                assert app._current_selected_id() is None
                # Must not raise.
                await pilot.press("enter")
                await pilot.pause()

        _run(body())

    def test_list_view_scrolls_to_keep_cursor_visible(self, ctx):
        """The list view scrolls so a cursor moved past the viewport stays visible.

        Bug 3: alt views must scroll to follow the cursor. With many tasks and
        a short terminal, moving the cursor well below the fold must advance
        the view's scroll offset so the highlighted row remains in view.
        """
        from doxtr_doto.cli.tui.widgets import ListView

        # Add enough tasks to exceed a short viewport.
        for i in range(40):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout
                await pilot.pause()
                list_view = app.query_one(ListView)
                assert list_view.max_scroll_y > 0  # content exceeds the box
                assert list_view.scroll_y == 0
                # Drive the cursor far below the fold.
                for _ in range(30):
                    await pilot.press("down")
                await pilot.pause()
                # The cursor advanced and the view scrolled to follow it.
                assert list_view.cursor == 30
                # The view scrolled at all (this still fails pre-fix, when the
                # view was a non-scrolling Static).
                assert list_view.scroll_y > 0
                # ...and the cursor line is within the scrolled viewport: at
                # or below the top edge, and above the bottom edge. This is
                # the robust invariant the fix guarantees, without pinning
                # scroll_y to the exact clamp boundary (fragile across
                # textual/platform viewport-geometry drift).
                cursor_line = list_view.cursor_line()
                visible_rows = list_view.size.height
                assert 0 < list_view.scroll_y <= cursor_line
                assert cursor_line - list_view.scroll_y < visible_rows

        _run(body())

    def test_list_navigation_block_jumps_near_margin_and_holds_mid_frame(self, ctx):
        """Fix 7: smart-scroll is wired into live list navigation.

        Proves end-to-end that ``scroll_to_cursor`` calls ``target_scroll_y``
        and that ``_last_cursor_line`` direction inference works in a real
        view: a single ``down`` that only moves the cursor *within* the frame
        (away from either margin) must not scroll at all, and the ``down``
        that crosses the bottom margin must jump a *block* (roughly
        ``SCROLL_JUMP`` rows), not a single line. Assertions are ranges/
        invariants so they stay robust to Textual geometry drift.
        """
        from doxtr_doto.cli.tui.widgets import ListView

        for i in range(60):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 16)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list layout
                await pilot.pause()
                list_view = app.query_one(ListView)
                assert list_view.max_scroll_y > 0
                assert list_view.scroll_y == 0
                height = list_view.size.height
                jump = ListView.SCROLL_JUMP

                # 1) A move that stays mid-frame (above the bottom margin) must
                #    not scroll: the view holds while the cursor is well inside
                #    the frame.
                await pilot.press("down")
                await pilot.pause()
                assert list_view.cursor == 1
                assert list_view.scroll_y == 0  # no mid-frame creep

                # 2) Drive the cursor until it crosses the bottom margin; the
                #    crossing move must block-jump (advance several rows at
                #    once), not creep one line.
                prev_scroll = list_view.scroll_y
                jumped = 0
                for _ in range(height):
                    before = list_view.scroll_y
                    await pilot.press("down")
                    await pilot.pause()
                    delta = list_view.scroll_y - before
                    if delta > 0:
                        jumped = delta
                        break
                # The first scroll was a block jump, not a single line, and it
                # advanced roughly SCROLL_JUMP rows (bounded generously so the
                # exact clamp/geometry does not make the test brittle).
                assert jumped >= 2
                assert jumped <= height + jump
                assert list_view.scroll_y > prev_scroll
                # The cursor stays within the scrolled viewport.
                cursor_line = list_view.cursor_line()
                assert list_view.scroll_y <= cursor_line
                assert cursor_line - list_view.scroll_y < height

        _run(body())

    def test_kanban_view_scrolls_to_keep_cursor_visible(self, ctx):
        """The kanban view scrolls so a card moved past the viewport stays visible."""
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Many open tasks pile into the single 'open' column.
        for i in range(40):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.max_scroll_y > 0
                # The first card is already fully visible: its top line at or
                # below the top edge and its bottom line at or above the
                # bottom edge. (With a card as tall as the viewport the view
                # may start slightly scrolled so the whole first card fits -
                # the fix keeps the *entire* card on screen, not just its top
                # line, so this is a range invariant rather than scroll_y==0.)
                card_height = board.cursor_span()
                height0 = board.size.height
                assert board.cursor_line() >= board.scroll_y
                assert board.cursor_line() + card_height - 1 <= board.scroll_y + height0 - 1
                for _ in range(30):
                    await pilot.press("down")
                await pilot.pause()
                assert board.row == 30
                # The board scrolled at all (fails pre-fix on the Static).
                assert board.scroll_y > 0
                # ...and the highlighted card's line sits within the scrolled
                # viewport (robust invariant, not the exact clamp boundary).
                cursor_line = board.cursor_line()
                visible_rows = board.size.height
                assert 0 < board.scroll_y <= cursor_line
                assert cursor_line - board.scroll_y < visible_rows

        _run(body())

    def test_kanban_whole_card_stays_visible_scrolling_down(self, ctx):
        """Scroll bug: the WHOLE selected card stays on screen pressing 'j'.

        Repro of the reported lag: each kanban card is a fixed multi-line
        block, but the shared smart-scroll used to treat the cursor as a
        single line, so from the third card down the selected card's bottom
        edge dropped below the viewport. After the fix (cursor_span driving
        target_scroll_y) the whole card - top AND bottom edge - must sit
        inside the visible region after every downward move.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        for i in range(12):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 28)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.max_scroll_y > 0  # cards overflow the viewport
                card_height = board.cursor_span()
                assert card_height > 1  # multi-line cards
                height = board.size.height
                # Press 'j' repeatedly; after each move the whole card (its
                # top line through its bottom line) must be visible.
                for _ in range(11):
                    await pilot.press("j")
                    await pilot.pause()
                    scroll_y = board.scroll_y
                    cursor_line = board.cursor_line()
                    assert cursor_line >= scroll_y
                    assert cursor_line + card_height - 1 <= scroll_y + height - 1

        _run(body())

    def test_kanban_whole_card_stays_visible_scrolling_up(self, ctx):
        """Symmetric scroll fix: the WHOLE card stays visible pressing 'k'.

        After scrolling to the bottom of a tall lane, pressing 'k' to walk
        back up must keep the entire selected card inside the viewport on
        every move (top edge not above the frame, bottom edge not below it).
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        for i in range(12):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 28)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert board.max_scroll_y > 0
                card_height = board.cursor_span()
                height = board.size.height
                # Walk to the bottom of the lane first.
                for _ in range(11):
                    await pilot.press("j")
                    await pilot.pause()
                assert board.row == 11
                # Now walk back up; the whole card must stay visible.
                for _ in range(11):
                    await pilot.press("k")
                    await pilot.pause()
                    scroll_y = board.scroll_y
                    cursor_line = board.cursor_line()
                    assert cursor_line >= scroll_y
                    assert cursor_line + card_height - 1 <= scroll_y + height - 1

        _run(body())

    def test_kanban_lanes_line_up_on_first_mount(self, ctx):
        """All kanban lanes lay out side by side immediately on first mount.

        Regression: at first mount Textual has not completed its initial
        layout pass when ``on_mount`` calls ``rebuild``, so the view's
        ``size.width`` is still 0 and the columns fell back to their natural
        (wide) width - which overflowed the viewport and wrapped the board
        into a 2-column grid until an arrow key triggered another rebuild.
        ``KanbanView.on_resize`` now re-renders from the cached columns once
        the real width is known, so every configured status lane shows up on
        the single header row from the start (no key press required).
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Four configured statuses -> four lanes that must line up at once.
        ctx.config.statuses = ["open", "in-progress", "blocked", "done"]
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                # The view has real geometry now, and the width came from the
                # even split of the live viewport (not the wide pre-mount
                # fallback), so the whole board row fits side by side.
                assert board._available_width() > 0
                live_width = KanbanView.column_width(board.columns, board._available_width())
                assert board._column_width == live_width
                # Every configured lane title is present on the single header
                # row - i.e. the board did NOT wrap into a 2-column grid where
                # some lanes would spill onto a later block.
                lines = board.rendered_text().split("\n")
                header = Text.from_markup(lines[0]).plain
                for status in ("open", "in-progress", "blocked", "done"):
                    assert status in header
                # ...and they appear left-to-right in configured order.
                positions = [header.index(s) for s in ("open", "in-progress", "blocked", "done")]
                assert positions == sorted(positions)

        _run(body())

    def test_kanban_board_fits_when_a_lane_shows_a_scrollbar(self, ctx):
        """The board row fits the usable width even when a lane scrollbar shows.

        Regression: ``_available_width`` returned ``size.width``, which still
        counts the columns a vertical scrollbar consumes. When one lane holds
        enough cards to force the view's scrollbar, the board row
        (``count * col_width + gaps``) was laid out to the too-wide
        ``size.width`` and so exceeded the real usable content width
        (``scrollable_content_region.width``, 1-2 cols narrower), making
        Textual soft-wrap the row - the rightmost lane's frame top was pushed
        under the leftmost lane. ``_available_width`` now returns the
        scrollbar-aware usable width, so the row always fits and never wraps.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Four lanes, with many cards in every lane so (a) the view must show
        # a vertical scrollbar (which narrows the usable content width) and (b)
        # every column renders full-width card frames, so the board row
        # actually reaches the computed column-grid budget.
        ctx.config.statuses = ["open", "in-progress", "blocked", "done"]
        for status in ctx.config.statuses:
            for i in range(10):
                actions.add_task(ctx, f"Task {status} {i}", status=status)
        app = self._app(ctx)

        async def body():
            # A width where the pre-fix code overflowed (82 -> size.width 78,
            # scrollable 76; 4 * 18 + 3 * 2 = 78 > 76).
            async with app.run_test(size=(82, 30)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                await pilot.pause()
                view = app.query_one(KanbanView)
                # The lane really does overflow, so the vertical scrollbar is
                # shown - otherwise this test would not exercise the bug.
                assert view.max_scroll_y > 0
                usable = view.scrollable_content_region.width
                # With the scrollbar visible the usable content width is
                # strictly narrower than size.width (the scrollbar columns).
                assert usable < view.size.width
                lines = view.rendered_text().split("\n")
                # No rendered board row exceeds the usable content width, so
                # Textual never soft-wraps the row (no frame corruption).
                for line in lines:
                    assert Text.from_markup(line).cell_len <= usable
                # All four lane headers are on the single first row, in order -
                # the board did not wrap into a stacked 2-column grid.
                header = Text.from_markup(lines[0]).plain
                for status in ("open", "in-progress", "blocked", "done"):
                    assert status in header
                positions = [header.index(s) for s in ("open", "in-progress", "blocked", "done")]
                assert positions == sorted(positions)

        _run(body())

    def test_kanban_available_width_equals_size_width_without_scrollbar(self, ctx):
        """Without a scrollbar the usable width equals ``size.width`` (unchanged).

        The scrollbar-aware ``_available_width`` must not change behaviour when
        no scrollbar is shown: ``scrollable_content_region.width`` equals
        ``size.width`` then, so the computed column width is exactly what the
        pre-fix ``size.width`` path produced.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        ctx.config.statuses = ["open", "in-progress", "blocked", "done"]
        app = self._app(ctx)

        async def body():
            # A tall viewport with only the fixture's few tasks: no lane
            # overflows, so no vertical scrollbar.
            async with app.run_test(size=(90, 40)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                view = app.query_one(KanbanView)
                # No overflow -> no scrollbar -> usable width == size.width.
                assert view.max_scroll_y == 0
                assert view.scrollable_content_region.width == view.size.width
                assert view._available_width() == view.size.width
                # The column width matches the pure size.width computation.
                expected = KanbanView.column_width(view.columns, view.size.width)
                assert view._column_width == expected

        _run(body())

    def test_kanban_board_refits_when_scrollbar_toggles_mid_session(self, ctx):
        """A scrollbar toggling mid-session re-fits the board (no overflow).

        Regression: a vertical scrollbar is drawn *inside* the view's region,
        so a lane growing past the scroll threshold toggles the scrollbar
        without changing the view's outer region size - Textual posts no
        ``Resize``, so ``on_resize`` does not fire. ``watch_show_vertical_
        scrollbar`` is the hook that re-renders the board at the new
        scrollbar-aware width on a pure toggle; without it the board would
        stay rendered at the pre-toggle (too-wide) width and the row would
        overflow the now-narrower usable content width. This simulates the
        toggle by narrowing ``scrollable_content_region`` and firing the
        watcher, then asserts the re-rendered row fits the narrower width.
        """
        from unittest.mock import PropertyMock, patch

        from rich.text import Text
        from textual.geometry import Region

        from doxtr_doto.cli.tui.widgets import KanbanView

        ctx.config.statuses = ["open", "in-progress", "blocked", "done"]
        for status in ctx.config.statuses:
            actions.add_task(ctx, f"Task {status}", status=status)
        app = self._app(ctx)

        async def body():
            # A wide, tall viewport so the board starts fitting its full width.
            async with app.run_test(size=(90, 40)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                view = app.query_one(KanbanView)
                full = view.scrollable_content_region.width
                assert view._available_width() == full
                narrowed = full - 2
                # Precondition: before the toggle the board is rendered to the
                # full width, so a row already exceeds the (narrower) usable
                # width a scrollbar would leave - i.e. the toggle genuinely
                # needs a re-render to avoid overflow.
                pre_lines = view.rendered_text().split("\n")
                assert max(Text.from_markup(line).cell_len for line in pre_lines) > narrowed
                # Simulate a scrollbar appearing: the content region narrows by
                # the scrollbar's columns while the view's outer region (and so
                # its ``size``) is unchanged - the pure-toggle case Textual
                # does NOT post a ``Resize`` for. Firing the layout watcher must
                # re-render the board at the narrower width.
                with patch.object(
                    type(view),
                    "scrollable_content_region",
                    new_callable=PropertyMock,
                    return_value=Region(0, 0, narrowed, view.size.height),
                ):
                    view.watch_show_vertical_scrollbar(True)
                    # The board re-fit to the narrower width: no rendered row
                    # exceeds it, so Textual never soft-wraps the row.
                    lines = view.rendered_text().split("\n")
                    for line in lines:
                        assert Text.from_markup(line).cell_len <= narrowed
                    # All four lanes stay side by side on the single header
                    # row (no collapse into a stacked 2-column grid).
                    header = Text.from_markup(lines[0]).plain
                    for status in ("open", "in-progress", "blocked", "done"):
                        assert status in header
                    positions = [
                        header.index(s) for s in ("open", "in-progress", "blocked", "done")
                    ]
                    assert positions == sorted(positions)
                # The column width tracked the narrowed usable width, not the
                # wider pre-toggle width - proving the watcher re-rendered.
                assert view._column_width == KanbanView.column_width(view.columns, narrowed)

        _run(body())

    def test_calendar_grid_stays_pinned_after_arrow_navigation(self, ctx):
        """Arrow/vim navigation must never scroll the month grid off the top.

        Feature 3: the month grid (header + weekday legend + week rows) stays
        pinned/visible; only the per-day task list below the grid scrolls.
        With many undated tasks the detail region is tall enough to make the
        content overflow a short terminal, so pre-fix the shared smart-scroll
        would push the grid header off the top. After pressing the arrow and
        vim navigation keys the grid header and weekday legend must still be
        rendered at the top of the viewport (``scroll_y == 0``).
        """
        from datetime import date

        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import CalendarView

        # Tall "no due date" detail region so content exceeds the viewport.
        for i in range(40):
            actions.add_task(ctx, f"Task {i}")
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.press("v")  # calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                # Pin the month so the grid layout is deterministic.
                calendar.selected = date(2099, 1, 1).isoformat()
                calendar.rebuild(app._tasks, today=date(2099, 1, 1))
                await pilot.pause()
                assert calendar.max_scroll_y > 0  # content overflows the box
                # Drive the selector around with every navigation key.
                for key in ("j", "j", "down", "down", "l", "right", "k", "h"):
                    await pilot.press(key)
                    await pilot.pause()
                    # The grid is pinned: the view never scrolls off the top.
                    assert calendar.scroll_y == 0
                # The month header + weekday legend remain the first rendered
                # lines (not scrolled away).
                rendered = Text.from_markup(calendar.rendered_text()).plain
                lines = rendered.split("\n")
                assert "January 2099" in lines[0]
                assert "Mo Tu We Th Fr Sa Su" in lines[1]

        _run(body())

    def test_tab_moves_kanban_card_forward_through_lanes(self, ctx):
        """Feature A: Tab moves the selected kanban card one lane forward.

        Each Tab press advances the selected card to the next status column (a
        status change via ``update_task``); the selection follows the card. In
        the last real column Tab is a no-op move (no wrap/crash), and a move
        that would land in the ``(other)`` column is likewise a no-op.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        # Configure a known set of status lanes.
        ctx.config.statuses = ["open", "in-progress", "done"]
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                moved = board.selected_id()
                assert moved is not None
                assert board.columns[0][0] == "open"
                assert board.col == 0
                # Tab moves the card open -> in-progress; selection follows.
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, KanbanView)
                assert board.col == 1
                assert board.selected_id() == moved
                assert actions.find_task(ctx, moved)["status"] == "in-progress"
                # Tab again: in-progress -> done (last real lane).
                await pilot.press("tab")
                await pilot.pause()
                assert board.col == 2
                assert board.selected_id() == moved
                assert actions.find_task(ctx, moved)["status"] == "done"
                # Tab from the last lane is a no-op move (no wrap/crash).
                await pilot.press("tab")
                await pilot.pause()
                assert board.col == 2
                assert actions.find_task(ctx, moved)["status"] == "done"

        _run(body())

    def test_shift_tab_moves_kanban_card_back_through_lanes(self, ctx):
        """Feature A: Shift+Tab moves the selected kanban card one lane back.

        The mirror of Tab: each press steps the card to the previous status
        column; from the first real lane it is a no-op move (no wrap/crash).
        """
        from doxtr_doto.cli.tui.widgets import KanbanView

        ctx.config.statuses = ["open", "in-progress", "done"]
        # Seed the single task in the last lane so there is room to move back.
        actions.update_task(ctx, "T-001", {"status": "done"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                # Select the card in the 'done' lane.
                for col_index, (name, _items) in enumerate(board.columns):
                    if name == "done":
                        board.col = col_index
                        board.row = 0
                moved = board.selected_id()
                assert moved is not None
                done_col = board.col
                # Shift+Tab moves done -> in-progress.
                await pilot.press("shift+tab")
                await pilot.pause()
                assert isinstance(app.focused, KanbanView)
                assert board.col == done_col - 1
                assert board.selected_id() == moved
                assert actions.find_task(ctx, moved)["status"] == "in-progress"
                # Shift+Tab again: in-progress -> open (first real lane).
                await pilot.press("shift+tab")
                await pilot.pause()
                assert board.col == 0
                assert actions.find_task(ctx, moved)["status"] == "open"
                # Shift+Tab from the first lane is a no-op move (no wrap).
                await pilot.press("shift+tab")
                await pilot.pause()
                assert board.col == 0
                assert actions.find_task(ctx, moved)["status"] == "open"

        _run(body())

    def test_tab_cycles_calendar_view_and_details(self, ctx):
        """Feature A: Tab cycles grid -> Due -> No-due -> details -> grid.

        The calendar view now has three internal focus regions (grid, the
        "Due" list, the "No due date" list); Tab walks through them and then
        into the shared details pane before looping back to the grid.
        """
        from doxtr_doto.cli.tui.widgets import CalendarView, TaskDetails

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_GRID
                # grid -> Due (still the view, now on the Due region).
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_DUE
                # Due -> No-due.
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_NO_DUE
                # No-due -> details pane.
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, TaskDetails)
                # details -> back to the grid.
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_GRID

        _run(body())

    def test_tab_keeps_focus_on_list_view(self, ctx):
        """The single-pane list layout keeps Tab focus on its one view."""
        from doxtr_doto.cli.tui.widgets import ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                assert isinstance(app.focused, ListView)
                await pilot.press("tab")
                await pilot.pause()
                # No second pane to cycle into; focus stays on the list view.
                assert isinstance(app.focused, ListView)

        _run(body())

    def test_shift_tab_cycles_panes_reverse_table(self, ctx):
        """Shift+Tab walks the table pane cycle in reverse.

        The forward Tab cycle is repo tree -> task list -> details; the
        reverse cycle is its exact mirror: repo tree -> details -> task list
        -> repo tree.
        """
        from doxtr_doto.cli.tui.widgets import RepoTree, TaskDetails, TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Starts focused on the task list.
                assert isinstance(app.focused, TaskList)
                await pilot.press("shift+tab")
                assert isinstance(app.focused, RepoTree)
                await pilot.press("shift+tab")
                assert isinstance(app.focused, TaskDetails)
                await pilot.press("shift+tab")
                assert isinstance(app.focused, TaskList)

        _run(body())

    def test_tab_still_cycles_panes_in_table_layout(self, ctx):
        """Regression (Feature A): Tab keeps cycling the 3 table panes.

        The kanban Tab/Shift+Tab card-move switch must not change the table
        layout: Tab still walks repo tree -> task list -> details.
        """
        from doxtr_doto.cli.tui.widgets import RepoTree, TaskDetails, TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert isinstance(app.focused, TaskList)
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, TaskDetails)
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, RepoTree)
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, TaskList)

        _run(body())

    def test_table_arrows_still_noop_and_tab_unchanged(self, ctx, store_file):
        """Regression (Feature A): table left/right stay a harmless no-op."""
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("left")
                await pilot.press("right")
                await pilot.press("h")
                await pilot.press("l")
                await pilot.pause()
                assert table.selected_id() == "T-001"

        _run(body())
        # No status changed in the table layout.
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_calendar_tab_and_arrows_unchanged_by_kanban_switch(self, ctx):
        """Regression (Feature A): calendar Tab + arrows keep their semantics.

        The kanban key switch is scoped to the kanban layout; in the calendar
        layout left/right still select the previous/next day and Tab drives
        the calendar's own grid -> Due -> No-due -> details region cycle (not
        the kanban card-move).
        """
        from datetime import date, timedelta

        from doxtr_doto.cli.tui.widgets import CalendarView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                start = date.fromisoformat(calendar.selected)
                # Arrows select the adjacent day (unchanged).
                await pilot.press("right")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start + timedelta(days=1)
                await pilot.press("left")
                await pilot.pause()
                assert date.fromisoformat(calendar.selected) == start
                # Tab drives the calendar's region cycle (grid -> Due), not
                # the kanban card-move: focus stays on the calendar view and
                # the focused region advances.
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_GRID
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_DUE

        _run(body())

    def test_kanban_lane_navigation_refreshes_details(self, ctx):
        """Feature A: navigating lanes refreshes the details pane for the card.

        Since Tab no longer moves the selection into details, lane navigation
        (left/right, h/l) must keep the details pane current for the newly
        selected card.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView, TaskDetails

        # Put the two tasks in different lanes so navigation changes selection.
        actions.update_task(ctx, "T-002", {"status": "in-progress"})
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                details = app.query_one(TaskDetails)
                assert board.selected_id() == "T-001"
                assert "First task" in str(details.render())
                await pilot.press("right")  # navigate to the in-progress lane
                await pilot.pause()
                assert board.selected_id() == "T-002"
                # Details auto-refreshed for the newly selected card.
                assert "Second task" in str(details.render())

        _run(body())

    def test_kanban_lane_count_stable_after_completion(self, ctx):
        """Feature B: completing a card keeps all configured lanes side by side.

        A completion-triggered rebuild (``d`` -> refresh_tasks ->
        KanbanView.rebuild) must not collapse the board into a 2-column grid.
        Before the fix, a rebuild that momentarily saw a width of 0 fell back
        to the natural wide column width and wrapped the lanes; now the last
        live width is cached and reused, so the configured lane count stays on
        the single header row across the completion.
        """
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        # Four configured statuses -> four lanes that must stay side by side.
        ctx.config.statuses = ["open", "in-progress", "blocked", "done"]
        # Several tasks so there is a card to complete without emptying a lane.
        for i in range(3):
            actions.add_task(ctx, f"Extra {i}")
        app = self._app(ctx)

        statuses = ("open", "in-progress", "blocked", "done")

        def _header_positions(board):
            header = Text.from_markup(board.rendered_text().split("\n")[0]).plain
            return [header.index(s) for s in statuses if s in header]

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                # Baseline: all four lanes on the single header row in order.
                before = _header_positions(board)
                assert len(before) == 4
                assert before == sorted(before)
                width_before = board._column_width
                # Complete the selected card (triggers a rebuild).
                await pilot.press("d")
                await pilot.pause()
                # The lane count/width stayed stable - no 2-column collapse.
                after = _header_positions(board)
                assert len(after) == 4
                assert after == sorted(after)
                assert board._column_width == width_before

        _run(body())

    def test_available_width_reuses_last_live_width_when_zero(self, ctx):
        """Feature B unit: a mounted view reporting width 0 reuses the cache.

        Directly exercises the caching contract in ``_available_width``: once a
        positive live width has been seen it is reused when the view's
        ``scrollable_content_region`` momentarily reports width 0, so
        ``column_width`` never falls back to the wide natural width that wraps
        the board.
        """
        from unittest.mock import PropertyMock, patch

        from textual.geometry import Region

        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                live = board._available_width()
                assert live > 0
                assert board._last_live_width == live
                # Force a mounted view to momentarily report width 0 via the
                # attribute ``_available_width`` actually reads
                # (``scrollable_content_region``, not ``size``): the cached
                # last-good width is reused instead of 0, so column_width
                # never falls back to the wide natural width.
                with patch.object(
                    type(board),
                    "scrollable_content_region",
                    new_callable=PropertyMock,
                    return_value=Region(0, 0, 0, 24),
                ):
                    assert board.scrollable_content_region.width == 0
                    assert board._available_width() == live
                # With the real geometry restored the live width is unchanged.
                assert board._available_width() == live
                # The derived per-column width at width 0 falls back to the
                # wide natural width, which the live even split stays below.
                collapsed = KanbanView.column_width(board.columns, 0)
                stable = KanbanView.column_width(board.columns, live)
                assert stable < collapsed

        _run(body())

    def test_shift_tab_cycles_calendar_view_and_details_reverse(self, ctx):
        """Shift+Tab walks the calendar region cycle in reverse.

        Forward Tab is grid -> Due -> No-due -> details -> grid; Shift+Tab is
        the exact mirror, so from the grid it steps straight to the details
        pane and then re-enters the view at its last region (No-due).
        """
        from doxtr_doto.cli.tui.widgets import CalendarView, TaskDetails

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                for _ in range(3):
                    await pilot.press("v")  # table -> ... -> calendar
                await pilot.pause()
                calendar = app.query_one(CalendarView)
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_GRID
                # grid -> details (reverse steps off the start of the regions).
                await pilot.press("shift+tab")
                await pilot.pause()
                assert isinstance(app.focused, TaskDetails)
                # details -> re-enter the view at the No-due region.
                await pilot.press("shift+tab")
                await pilot.pause()
                assert isinstance(app.focused, CalendarView)
                assert calendar.focus_region == CalendarView.REGION_NO_DUE

        _run(body())

    def test_shift_tab_keeps_focus_on_list_view(self, ctx):
        """The single-pane list layout keeps Shift+Tab focus on its one view."""
        from doxtr_doto.cli.tui.widgets import ListView

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                assert isinstance(app.focused, ListView)
                await pilot.press("shift+tab")
                await pilot.pause()
                # No second pane to cycle into; focus stays on the list view.
                assert isinstance(app.focused, ListView)

        _run(body())

    def test_back_tab_key_name_triggers_reverse_cycle(self, ctx):
        """The literal ``back_tab`` key name also drives the reverse cycle.

        Regression: a real terminal may deliver the physical Shift+Tab as the
        key named ``back_tab`` rather than ``shift+tab``. Binding only
        ``shift+tab`` left reverse cycling silently dead in those terminals
        (Pilot's ``press("shift+tab")`` masked it because it injects the
        already-normalized key name). Both key names are now bound to the
        reverse-cycle actions at the app and widget level, so pressing
        ``back_tab`` cycles exactly like ``shift+tab``.
        """
        from doxtr_doto.cli.tui.widgets import KanbanView, RepoTree, TaskList

        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                # Table layout: back_tab mirrors Tab's reverse
                # (task list -> repo tree).
                assert isinstance(app.focused, TaskList)
                await pilot.press("back_tab")
                await pilot.pause()
                assert isinstance(app.focused, RepoTree)
                # Kanban layout: back_tab moves the selected card one lane
                # back (the reverse of Tab moving it forward). From the first
                # real lane this is a no-op move (no wrap); focus stays on the
                # board. First advance it one lane with Tab so there is room to
                # move back.
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView)
                assert isinstance(app.focused, KanbanView)
                assert board.col == 0
                moved = board.selected_id()
                await pilot.press("tab")  # move card forward one lane
                await pilot.pause()
                assert board.col == 1
                assert board.selected_id() == moved
                # back_tab moves it back to the first lane.
                await pilot.press("back_tab")
                await pilot.pause()
                assert isinstance(app.focused, KanbanView)
                assert board.col == 0
                assert board.selected_id() == moved

        _run(body())


# ---------------------------------------------------------------------------
# Long values: layout / overflow handling
# ---------------------------------------------------------------------------
def _visible_width(markup: str) -> int:
    """Return a markup line's *visible* width (screen columns, markup ignored)."""
    from rich.text import Text

    return Text.from_markup(markup).cell_len


def _plain(markup: str) -> str:
    """Return a markup line's plain text (Textual tags stripped)."""
    from rich.text import Text

    return Text.from_markup(markup).plain


class TestLongValuesPureLayout:
    """Pure-logic tests that long field values never break a view's layout.

    Exercises the ``format_*`` classmethods directly (no live terminal) with a
    task whose id/title/body/tags/assignee are all far wider than any pane, so
    the structural guarantees - cells truncated to their column, bodies wrapped
    to the inner width, and nothing silently dropped - are asserted
    deterministically.
    """

    def test_table_row_preserves_long_id_and_title(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        row = TaskList.format_row(_long_task())
        # DataTable owns column sizing, so the row cells carry the full values
        # verbatim; the id and title must survive untruncated into the table.
        # The Title cell is prefixed with the tree expand/collapse indicator
        # (a leaf's blank glyph for this flat task), so strip it before the
        # full-title check.
        assert row[5] == LONG_ID
        assert row[6] == TaskList.format_tree_prefix(0, False, False) + LONG_TITLE
        # Long tags are rendered as badges and all survive.
        tag_cell = _plain(row[7])
        for tag in LONG_TAGS:
            assert tag in tag_cell

    def test_list_line_carries_full_id_and_title(self):
        from doxtr_doto.cli.tui.widgets import ListView

        line = ListView.format_line(_long_task(), highlighted=True)
        plain = _plain(line)
        # The list is one compact line per task; it does not pre-truncate, so
        # the full id and the full title are present (the pane scrolls/wraps).
        assert LONG_ID in plain
        assert LONG_TITLE in plain
        # Highlighted rows wrap the whole line in a reverse span.
        assert line.startswith("[reverse]")

    def test_list_row_height_grows_when_the_line_wraps(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        line = ListView.format_line(_long_task(), highlighted=False)
        # At a wide width the long single line still wraps to several display
        # lines; at a very wide width it is one line. Either way row_height
        # reflects the real wrapped height (never a bogus 0).
        narrow = view.row_height(line, width=40)
        wide = view.row_height(line, width=1000)
        assert narrow > 1
        assert wide == 1

    def test_kanban_card_body_wraps_to_inner_width(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 24
        card = KanbanView.format_card(_long_task(), highlighted=False, width=width)
        # The first line is the ID+due line; every body line must fit the
        # column's inner width so the long title never spills sideways.
        for body_line in card[1:]:
            assert _visible_width(body_line) <= width

    def test_kanban_first_line_truncates_long_id_via_pad_cell(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # A card's first line carries the (very long) id; when the board packs
        # columns side by side pad_cell truncates each cell to the column
        # width, so a long id can never bleed into the neighbouring column.
        first = KanbanView.format_card_first_line(_long_task(), show_priority=False)
        padded = KanbanView.pad_cell(first, 20)
        assert _visible_width(padded) == 20

    def test_kanban_board_rows_never_exceed_the_column_grid(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        statuses = ["open", "in-progress", "done"]
        columns = KanbanView.bucket_by_status([_long_task()], statuses)
        width = 24  # deliberately narrower than the long id
        board = KanbanView.format_board(columns, 0, 0, width=width, show_priority=False)
        ncols = len(columns)
        gap = len(KanbanView.COLUMN_GAP)
        budget = ncols * width + (ncols - 1) * gap
        # Every rendered board row stays within the column grid: no card (not
        # even the long-id first line) spills past its column boundary.
        for board_row in board.split("\n"):
            assert _visible_width(board_row) <= budget

    def test_kanban_min_card_width_grows_to_fit_long_id_but_is_bounded(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        columns = KanbanView.bucket_by_status([_long_task()], ["open"])
        minimum = KanbanView.min_card_width(columns)
        first = KanbanView.format_card_first_line(_long_task(), show_priority=False)
        # The minimum column width is at least wide enough for the long id's
        # first line (so an unclamped board shows it in full) ...
        assert minimum >= _visible_width(first)
        # ... and never below the configured floor.
        assert minimum >= KanbanView.MIN_COLUMN_WIDTH

    def test_details_pane_includes_every_long_field(self):
        from doxtr_doto.cli.tui.widgets import TaskDetails

        details = TaskDetails.format_details(_long_task(), [])
        plain = _plain(details)
        # The scrollable details pane renders every field; none is dropped.
        assert LONG_ID in plain
        assert LONG_TITLE in plain
        assert LONG_ASSIGNEE in plain
        # The body is present (wrapping/scrolling is the pane's job).
        assert "deliberately long description body" in plain
        for tag in LONG_TAGS:
            assert tag in plain

    def test_details_pane_shows_parent_when_set(self):
        from doxtr_doto.cli.tui.widgets import TaskDetails

        task = {"id": "C-1", "title": "Child", "status": "open", "parent": "P-1"}
        plain = _plain(TaskDetails.format_details(task, []))
        assert "Parent: P-1" in plain

    def test_details_pane_omits_parent_when_absent(self):
        from doxtr_doto.cli.tui.widgets import TaskDetails

        # A top-level task (no ``parent``) renders no Parent line.
        task = {"id": "T-1", "title": "Top-level", "status": "open"}
        plain = _plain(TaskDetails.format_details(task, []))
        assert "Parent:" not in plain
        # An explicit None parent is likewise omitted.
        task_none = {"id": "T-2", "title": "Also top-level", "status": "open", "parent": None}
        assert "Parent:" not in _plain(TaskDetails.format_details(task_none, []))


#: Free-text titles that contain ``[``/``]`` which rich/Textual would
#: otherwise parse as style tags: a style-tag lookalike that silently drops
#: text, a bare ``[]``, and ``[/]`` (an unbalanced closing tag that raises
#: ``MarkupError`` when parsed).
BRACKET_TITLES = ["[WIP] fix the thing", "[red] colored", "[] empty", "[/] slash"]


def _bracket_task(status: str = "open", title: str = "[WIP] fix", **overrides):
    """Return a task whose id/title/tags carry markup-significant brackets."""
    task = {
        "id": "[id-1]",
        "title": title,
        "status": status,
        "priority": "high",
        "tags": ["[tag]", "plain"],
        "due": "2026-03-01",
    }
    task.update(overrides)
    return task


class TestBracketTitlesRenderLiterally:
    """Free text with ``[``/``]`` must render literally, not as a style tag.

    A title such as ``"[WIP] fix"`` (or a bare ``"[]"``) is otherwise parsed as
    rich/Textual markup: the bracketed run is silently dropped, visible-width
    measurement shrinks so framed kanban cards misalign, and a bare ``"[/]"``
    raises ``MarkupError``. Every ``format_*`` surface must escape free text so
    the brackets survive and occupy their true width - matching the CLI card
    builder, which already escapes via ``escape_markup``.
    """

    def test_kanban_card_rows_stay_square_with_bracket_title(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 24
        for title in BRACKET_TITLES:
            card = KanbanView.format_card(_bracket_task(title=title), highlighted=True, width=width)
            # Every framed row - borders and body - must be exactly the column
            # width; an un-escaped ``[tag]`` would shrink the measured width
            # and the right border would no longer line up.
            for row in card:
                assert _visible_width(row) == width, (title, row)
            # The literal bracket text survives into the card body.
            plain = "".join(_plain(row) for row in card)
            assert title in plain, (title, plain)

    def test_table_row_cells_parse_and_keep_brackets(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        for title in BRACKET_TITLES:
            row = TaskList.format_row(_bracket_task(title=title))
            # The id/title/tag cells must parse as markup (``[/]`` would raise)
            # and render the brackets literally. The Title cell carries the
            # leading tree indicator (a leaf blank here), so strip it first.
            assert _plain(row[5]) == "[id-1]"
            prefix = TaskList.format_tree_prefix(0, False, False)
            assert _plain(row[6]) == prefix + title
            assert "[tag]" in _plain(row[7])

    def test_list_line_renders_bracket_title_literally(self):
        from doxtr_doto.cli.tui.widgets import ListView

        for title in BRACKET_TITLES:
            line = ListView.format_line(_bracket_task(title=title), highlighted=False)
            assert title in _plain(line), (title, line)

    def test_calendar_entry_renders_bracket_title_literally(self):
        from doxtr_doto.cli.tui.widgets import CalendarView

        for title in BRACKET_TITLES:
            entry = CalendarView.format_entry(_bracket_task(title=title), highlighted=True)
            assert title in _plain(entry), (title, entry)

    def test_repo_tree_leaf_renders_bracket_name_literally(self):
        from doxtr_doto.cli.tui.widgets import RepoTree

        # The current-repo and other-repo branches both escape the name.
        here = RepoTree.format_repo("[repo]", "[repo]")
        other = RepoTree.format_repo("[repo]", "elsewhere")
        assert "[repo]" in _plain(here)
        assert "[repo]" in _plain(other)

    def test_detail_card_lines_parse_and_keep_brackets(self):
        from doxtr_doto.cli.output import build_task_detail_lines

        # The full-detail card viewer (CardViewerScreen) renders these shared
        # lines through Textual markup, so a bracketed title must survive
        # there too (``[/]`` would raise MarkupError if unescaped).
        for title in BRACKET_TITLES:
            lines = build_task_detail_lines(_bracket_task(title=title))
            joined = "\n".join(lines)
            assert title in _plain(joined), (title, joined)
            # The detail title is intentionally *not* accent-highlighted (it is
            # the shared CLI/TUI builder, which stays colour-neutral); pin that
            # so a future change cannot silently diverge.
            assert "#" not in lines[0]

    def test_details_pane_body_keeps_markdown_link_text(self):
        from doxtr_doto.cli.tui.widgets import TaskDetails

        # The table-layout detail pane renders the task body through Textual
        # markup. A body containing a Markdown link ``[text](url)`` must keep
        # its ``[text]`` run: without escaping, Textual parses ``[link text]``
        # as a style tag and drops it, leaving only ``(url)`` in the preview
        # (the bug: the bracketed link text disappears although it is present
        # when editing).
        task = _bracket_task(title="plain", body="see [link text](http://example.com) for details")
        plain = _plain(TaskDetails.format_details(task, []))
        assert "[link text]" in plain, plain
        # Guard against the regression: the ``(url)``-only remnant must not be
        # the whole link rendering.
        assert "see [link text](http://example.com) for details" in plain

    def test_kanban_body_handles_a_bracket_run_split_across_lines(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        # A single bracket token longer than the card wraps across body rows;
        # each wrapped fragment is escaped independently, so the card must stay
        # square and never raise (the run just renders plain, as documented).
        width = 16
        title = "[" + "x" * 40 + "]"
        card = KanbanView.format_card(_bracket_task(title=title), highlighted=False, width=width)
        for row in card:
            assert _visible_width(row) == width, row

    def test_kickstart_modal_body_renders_bracket_candidate(self):
        from doxtr_doto.cli.tui.app import KickstartScreen
        from doxtr_doto.cli.tui.nudge import Candidate

        cand = Candidate(key="1", ref="T-001", title="[WIP] fix", priority="high")
        body = KickstartScreen([cand])._body()
        # The modal body is Textual markup; it must parse (``[/]`` safe) and
        # show the bracketed title literally.
        assert "[WIP] fix" in _plain(body)


class TestBracketTitlesAccentHighlight:
    """The ``[...]`` runs of a title are drawn in the active theme accent.

    When the live TUI resolves the theme accent and publishes it onto the
    overridable ``TitleHighlight.BRACKET_HIGHLIGHT_STYLE`` class attribute,
    every title ``format_*`` surface must colour the bracketed run with that
    hue (the same colour the Textual footer uses for key labels like ``tab``)
    while still rendering the brackets literally and keeping the title's true
    visible width. The highlight is a concrete colour so it resolves in *both*
    rich (kanban/DataTable width measurement) and Textual markup.
    """

    ACCENT = "#ffa62b"

    def setup_method(self):
        from doxtr_doto.cli.tui.widgets import TitleHighlight

        self._prev = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
        TitleHighlight.BRACKET_HIGHLIGHT_STYLE = self.ACCENT

    def teardown_method(self):
        from doxtr_doto.cli.tui.widgets import TitleHighlight

        # Restore the previous value so other tests stay unaffected.
        TitleHighlight.BRACKET_HIGHLIGHT_STYLE = self._prev

    @staticmethod
    def _textual_spans(markup: str):
        from textual.content import Content

        return Content.from_markup(markup)

    def test_escape_title_colours_bracket_run_only(self):
        from doxtr_doto.cli.tui.theme import escape_title

        content = self._textual_spans(escape_title("[WIP] fix", self.ACCENT))
        # The brackets render literally and keep their true width ...
        assert content.plain == "[WIP] fix"
        assert content.cell_length == len("[WIP] fix")
        # ... and exactly the bracketed run (positions 0..5, ``[WIP]``) is the
        # accent-styled span - the trailing `` fix`` is unstyled.
        assert len(content.spans) == 1
        span = content.spans[0]
        assert content.plain[span.start : span.end] == "[WIP]"
        assert self.ACCENT in str(span.style)

    def test_escape_title_highlights_every_bracket_run(self):
        from doxtr_doto.cli.tui.theme import escape_title

        content = self._textual_spans(escape_title("a [x] b [y] c", self.ACCENT))
        assert content.plain == "a [x] b [y] c"
        # Both bracketed runs are accent-styled.
        runs = [content.plain[s.start : s.end] for s in content.spans]
        assert runs == ["[x]", "[y]"]
        assert all(self.ACCENT in str(s.style) for s in content.spans)

    def test_classmethod_escape_title_uses_the_class_attribute(self):
        from doxtr_doto.cli.tui.widgets import ListView, TitleHighlight

        # The overridable classmethod seam reads the (set) class attribute ...
        assert self.ACCENT in ListView.escape_title("[WIP] fix")

        # ... and a subclass can disable/retint the highlight per widget by
        # overriding just the attribute (the frame_style idiom).
        class _Plain(TitleHighlight):
            BRACKET_HIGHLIGHT_STYLE = ""

        assert "\\[WIP]" in _Plain.escape_title("[WIP] fix")
        assert self.ACCENT not in _Plain.escape_title("[WIP] fix")

    def test_kanban_card_body_carries_accent_and_stays_square(self):
        from doxtr_doto.cli.tui.widgets import KanbanView

        width = 24
        card = KanbanView.format_card(
            _bracket_task(title="[WIP] fix"), highlighted=False, width=width
        )
        # Still perfectly framed with the accent applied ...
        for row in card:
            assert _visible_width(row) == width
        # ... and the accent colour is present in the body markup.
        assert any(self.ACCENT in row for row in card)

    def test_all_title_surfaces_carry_accent(self):
        from doxtr_doto.cli.tui.widgets import (
            CalendarView,
            ListView,
            TaskDetails,
            TaskList,
        )

        task = _bracket_task(title="[WIP] fix")
        # List / table / calendar / details all route titles through the
        # shared ``escape_title`` seam, so every surface carries the accent.
        assert self.ACCENT in ListView.format_line(task, highlighted=False)
        assert self.ACCENT in TaskList.format_row(task)[6]
        assert self.ACCENT in CalendarView.format_entry(task, highlighted=False)
        assert self.ACCENT in TaskDetails.format_details(task, [])

    def test_no_style_leaves_titles_colour_free(self):
        from doxtr_doto.cli.tui.widgets import ListView, TitleHighlight

        TitleHighlight.BRACKET_HIGHLIGHT_STYLE = ""
        line = ListView.format_line(_bracket_task(title="[WIP] fix"), highlighted=False)
        # With no accent set the title is escaped but uncoloured, and the
        # brackets still render literally.
        assert self.ACCENT not in line
        assert "[WIP] fix" in _plain(line)


class TestLongValuesLiveLayout:
    """Pilot-driven tests that long values render cleanly in a live TUI.

    Drives the real app across every layout (table / list / kanban / calendar)
    and the details pane at both a normal and a cramped terminal size, so the
    overflow handling is exercised against Textual's actual layout engine - not
    just the pure classmethods.
    """

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        # Render the single current repo's tasks; pin LOCAL scope (the app now
        # defaults to GLOBAL, which would show nothing for the unregistered
        # current repo these fixtures use).
        app.scope = DisplayScope.LOCAL
        return app

    def test_every_layout_renders_long_task_without_error(self, long_ctx):
        from doxtr_doto.cli.tui.widgets import CalendarView, KanbanView, ListView

        app = self._app(long_ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                assert app.query_one(ListView).row_ids == [LONG_ID]
                assert LONG_ID in app.query_one(ListView).rendered_text()
                await pilot.press("v")  # kanban
                await pilot.pause()
                board = app.query_one(KanbanView).rendered_text()
                # The long id renders on the board, middle-truncated to the
                # live column width (:meth:`KanbanView.truncate_id` keeps the
                # id's head and tail with an ellipsis replacing the dropped
                # middle). The exact surviving head/tail length depends on how
                # narrow the lanes are at this viewport width, so assert the
                # width-robust invariants: the id was truncated (its ellipsis
                # is on the board) and the id's head/tail characters survive -
                # rather than a middle substring, which only fit before the
                # lanes were laid out at the real viewport width.
                plain = _plain(board)
                assert KanbanView.ID_ELLIPSIS in plain
                # The id's first and last characters survive the middle
                # truncation at any width.
                assert LONG_ID[0] in plain
                assert LONG_ID[-1] in plain
                await pilot.press("v")  # calendar
                await pilot.pause()
                assert app.query_one(CalendarView) is not None

        _run(body())

    def test_list_cursor_stays_in_view_with_wrapping_rows(self, tmp_path, env):
        from doxtr_doto.cli.tui.widgets import ListView

        # A store of many long-title tasks: every row wraps to several display
        # lines, so the smart-scroll follow (cursor_line) must account for the
        # wrapped heights or the highlighted row scrolls out of the pane.
        store_path = tmp_path / "many" / ".doto" / "tasks.json"
        store_path.parent.mkdir(parents=True)
        tasks = {}
        for i in range(30):
            t = _long_task()
            t.pop("id")
            tasks[f"{LONG_ID}-{i:02d}"] = t
        store_path.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": tasks,
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_path)
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        app = self._app(ctx)

        async def body():
            async with app.run_test(size=(60, 18)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.pause()
                view = app.query_one(ListView)
                # The content really does overflow (rows wrap), otherwise the
                # test would not exercise the follow-scroll path.
                assert view.max_scroll_y > 0
                for _ in range(29):
                    await pilot.press("j")
                    await pilot.pause()
                    top = int(view.scroll_y)
                    height = view.scrollable_content_region.height
                    cursor = view.cursor_line()
                    # The highlighted row's starting display line is always
                    # inside the visible window - it never scrolls out of view.
                    assert top <= cursor <= top + height - 1

        _run(body())

    def test_kanban_board_fits_the_grid_in_a_narrow_terminal(self, long_ctx):
        from rich.text import Text

        from doxtr_doto.cli.tui.widgets import KanbanView

        app = self._app(long_ctx)

        async def body():
            async with app.run_test(size=(48, 20)) as pilot:
                await pilot.pause()
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                view = app.query_one(KanbanView)
                width = view._column_width
                columns = view.columns
                ncols = len(columns)
                gap = len(KanbanView.COLUMN_GAP)
                budget = ncols * width + (ncols - 1) * gap
                # Even with a long id forcing a wide minimum column, every
                # rendered board row stays within the computed grid budget, so
                # no card spills into its neighbour.
                for line in view.rendered_text().split("\n"):
                    assert Text.from_markup(line).cell_len <= budget

        _run(body())

    def test_details_pane_shows_long_fields_in_live_app(self, long_ctx):
        from doxtr_doto.cli.tui.widgets import TaskDetails

        app = self._app(long_ctx)

        async def body():
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                details = app.query_one(TaskDetails)
                content = str(details.content)
                # The default table layout wires the cursor task into the
                # details pane; its long fields are all present - including the
                # id, which a raw store load would have dropped (regression:
                # the details pane rendered an empty [bold][/bold] id).
                assert LONG_ID in content
                assert "Donald Duck" in content
                assert LONG_ASSIGNEE in content

        _run(body())


@pytest.fixture
def reposition_store_file(tmp_path):
    """A JSON store with a long ``open`` list and a single ``in-progress`` task.

    Thirty ``open`` tasks (enough to overflow a short viewport in the list and
    kanban layouts) plus one ``in-progress`` task pinned at the top of its
    lane, so a Pilot test can scroll to the bottom of the long column and then
    switch (lane or layout) to the short destination and assert the viewport
    repositioned so the selected task is visible (the last unchecked feature).
    """
    store_path = tmp_path / "repoReposition" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    tasks = {
        f"T-{i:03d}": {
            "title": f"Open task {i}",
            "status": "open",
            "priority": "medium",
            "tags": [],
            "worklogs": [],
        }
        for i in range(30)
    }
    tasks["P-001"] = {
        "title": "Only in-progress task",
        "status": "in-progress",
        "priority": "high",
        "tags": [],
        "worklogs": [],
    }
    store_path.write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2024-01-01T00:00:00",
                "tasks": tasks,
                "series": {},
            }
        )
    )
    return store_path


@pytest.fixture
def reposition_ctx(reposition_store_file, env):
    """A DotoContext wired to the long-list / short-lane reposition store."""
    config = load_config(json_path=reposition_store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


class TestSelectedTaskAlwaysVisible:
    """Live-app tests for the always-reposition feature (last unchecked item).

    After any *discontinuous* selection change - a kanban lane switch, a
    layout cycle that re-selects a task, or a select-by-id - the viewport must
    reposition so the whole selected task is visible. These drive the real
    :class:`~doxtr_doto.cli.tui.app.DotoApp` through the Pilot so the wiring
    (``_kanban_navigate`` / ``_cycle_layout`` / ``select_task``) is exercised
    end to end, not just the widget seam.
    """

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        # Render the single current repo's tasks; pin LOCAL scope (the app
        # defaults to GLOBAL, which would show nothing for the unregistered
        # current repo this fixture uses).
        app.scope = DisplayScope.LOCAL
        return app

    def test_kanban_lane_switch_repositions_selected_card(self, reposition_ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView
        from doxtr_doto.enums import TuiLayout

        app = self._app(reposition_ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                # Switch to the kanban layout.
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                assert app.layout_view == TuiLayout.KANBAN
                board = app.query_one(KanbanView)
                assert board.max_scroll_y > 0  # the open lane overflows

                # Jump to the bottom of the long 'open' lane.
                await pilot.press("shift+down")
                await pilot.pause()
                assert board.scroll_y > 0  # frame scrolled down

                # Switch right to the single-card 'in-progress' lane. The card
                # is at the top, so the viewport must reposition to show it.
                await pilot.press("l")
                await pilot.pause()
                assert board.selected_id() == "P-001"
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                height = board.size.height
                assert board.scroll_y <= top  # card top visible
                assert bottom < board.scroll_y + height  # card bottom visible

        _run(body())

    def test_layout_switch_repositions_selected_task(self, reposition_ctx):
        from doxtr_doto.cli.tui.widgets import KanbanView
        from doxtr_doto.enums import TuiLayout

        app = self._app(reposition_ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                # Enter the kanban layout and scroll its long 'open' lane to
                # the bottom so the view carries a deep, stale scroll offset.
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.pause()
                assert app.layout_view == TuiLayout.KANBAN
                board = app.query_one(KanbanView)
                assert board.max_scroll_y > 0
                await pilot.press("shift+down")  # jump to bottom of the lane
                await pilot.pause()
                deep = board.scroll_y
                assert deep > 0

                # Relocate the kanban selection back to the top card and
                # re-anchor the smart-scroll baseline *without* repositioning,
                # so the view is left scrolled deep while its selection sits at
                # the top - the exact stale state a return visit produces.
                # ``apply_layout`` only toggles widget visibility (it does not
                # rebuild), so this deep offset survives the layout switch.
                board.row = 0
                board._sync_scroll_anchor()
                top = board.cursor_line()
                height = board.size.height
                assert not (board.scroll_y <= top < board.scroll_y + height)

                # Cycle away to the list and back to the kanban. The
                # ``_cycle_layout`` reposition on the newly active kanban view
                # must pull the selected top card back into view; without that
                # wiring the stale deep offset would remain and this assertion
                # would fail.
                await pilot.press("v")  # calendar
                await pilot.press("v")  # time
                await pilot.press("v")  # table
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban (active again)
                await pilot.pause()
                assert app.layout_view == TuiLayout.KANBAN
                board = app.query_one(KanbanView)
                top = board.cursor_line()
                bottom = top + board.cursor_span() - 1
                height = board.size.height
                assert board.scroll_y <= top  # card top visible
                assert bottom < board.scroll_y + height  # card bottom visible
                assert board.scroll_y < deep  # repositioned up from the deep offset

        _run(body())

    def test_cycle_into_calendar_keeps_grid_pinned(self, reposition_ctx):
        """Cycling into the calendar keeps its month grid pinned to the top.

        The calendar overrides
        :meth:`~doxtr_doto.cli.tui.widgets.CalendarView.ensure_cursor_visible`
        to delegate to its pinned-grid scroll, so the layout-cycle reposition
        (:meth:`~doxtr_doto.cli.tui.app.DotoApp._cycle_layout`) that pulls a
        list/kanban selection on screen instead keeps the calendar's grid
        header at the top (``scroll_y == 0``) rather than scrolling to a
        selected day. Exercises the ``CalendarView`` override end to end via
        the ``_cycle_layout`` wiring, the only path that reaches it.
        """
        from doxtr_doto.cli.tui.widgets import CalendarView
        from doxtr_doto.enums import TuiLayout

        app = self._app(reposition_ctx)

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                # Cycle TABLE -> LIST -> KANBAN -> CALENDAR.
                await pilot.press("v")  # list
                await pilot.press("v")  # kanban
                await pilot.press("v")  # calendar (CalendarView override runs)
                await pilot.pause()
                assert app.layout_view == TuiLayout.CALENDAR
                cal = app.query_one(CalendarView)
                # The pinned grid keeps the view at the top.
                assert cal.scroll_y == 0

        _run(body())

    def test_calendar_ensure_cursor_visible_delegates_to_pinned_grid(self):
        """The CalendarView override repositions to the pinned-grid offset (0).

        A direct unit check that
        :meth:`~doxtr_doto.cli.tui.widgets.CalendarView.ensure_cursor_visible`
        delegates to the pinned-grid scroll rather than the list/kanban
        span-clamp: even when the view carries a positive offset, the override
        clamps it back to 0 so the month grid header stays on screen.
        """
        from textual.app import App, ComposeResult

        from doxtr_doto.cli.tui.widgets import CalendarView

        tasks = [
            {"id": f"T-{i:03d}", "status": "open", "title": f"task {i}", "due": "2024-01-15"}
            for i in range(40)
        ]

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield CalendarView(id="cal")

        app = _Harness()

        async def body():
            async with app.run_test(size=(80, 12)) as pilot:
                await pilot.pause()
                cal = app.query_one("#cal", CalendarView)
                cal.rebuild(tasks)
                cal.focus()
                await pilot.pause()

                # Force a stale positive offset, then let the override pin it.
                cal.scroll_to(y=5, animate=False)
                await pilot.pause()
                cal.ensure_cursor_visible()
                await pilot.pause()
                assert cal.scroll_y == 0  # grid pinned to the top

        _run(body())


@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")
class TestConflictResolveDialog:
    """Pilot tests for the ``C r`` calendar-sync conflict resolver dialog."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL
        return app

    def _flag_conflict(self, store_file):
        """Give T-001 an unresolved body conflict stash on disk."""
        data = _load(store_file)
        data["tasks"]["T-001"].update(
            {
                "body": "<<<<<<< local\nLOCAL\n=======\nREMOTE\n>>>>>>> remote",
                "sync_conflict": True,
                "_sync": {
                    "conflict": {
                        "detected": "2024-01-01T00:00:00",
                        "fields": [
                            {
                                "field": "body",
                                "base": "l1\nBASE\nl3",
                                "local": "l1\nLOCAL\nl3",
                                "remote": "l1\nREMOTE\nl3",
                                "both": "<<<<<<< local\nLOCAL\n=======\nREMOTE\n>>>>>>> remote",
                            }
                        ],
                    }
                },
            }
        )
        store_file.write_text(json.dumps(data))

    def test_resolve_keep_remote_clears_conflict(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import ConflictResolveScreen

        self._flag_conflict(store_file)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "r")
                await pilot.pause()
                assert isinstance(app.screen, ConflictResolveScreen)
                await pilot.press("r")  # keep remote
                await pilot.pause()

        _run(body())
        t = _load(store_file)["tasks"]["T-001"]
        assert t["body"] == "l1\nREMOTE\nl3"
        assert t["sync_conflict"] is False
        assert t["_sync"]["conflict"] is None

    def test_resolve_cancel_leaves_conflict(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import ConflictResolveScreen

        self._flag_conflict(store_file)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "r")
                await pilot.pause()
                assert isinstance(app.screen, ConflictResolveScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())
        t = _load(store_file)["tasks"]["T-001"]
        # Untouched: still flagged, markers still present.
        assert t["sync_conflict"] is True
        assert "<<<<<<<" in t["body"]

    def test_resolve_noop_when_no_conflict(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import ConflictResolveScreen

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "r")
                await pilot.pause()
                # No conflict on the selected task -> no dialog is pushed.
                assert not isinstance(app.screen, ConflictResolveScreen)

        _run(body())

    def _flag_legacy_conflict(self, store_file):
        """Flag T-001 with body markers but NO structured stash (legacy merge)."""
        data = _load(store_file)
        data["tasks"]["T-001"].update(
            {
                "body": (
                    "shared\n\n<<<<<<< local (doto)\nLOCAL note\n"
                    "=======\nREMOTE note\n>>>>>>> remote (calendar)"
                ),
                "sync_conflict": True,
                "_sync": {"rst_file": None, "snapshot": None},
            }
        )
        store_file.write_text(json.dumps(data))

    def test_resolve_legacy_marker_task_from_dialog(self, ctx, store_file):
        """A task with markers but no stash is resolvable via the dialog."""
        from doxtr_doto.cli.tui.app import ConflictResolveScreen

        self._flag_legacy_conflict(store_file)
        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "r")
                await pilot.pause()
                assert isinstance(app.screen, ConflictResolveScreen)
                await pilot.press("l")  # keep local
                await pilot.pause()

        _run(body())
        t = _load(store_file)["tasks"]["T-001"]
        assert "LOCAL note" in t["body"]
        assert "<<<<<<<" not in t["body"]
        assert t["sync_conflict"] is False
        assert t["_sync"]["conflict"] is None


@pytest.fixture
def tree_store_file(tmp_path):
    """A JSON store with a 3-level parent/child task tree plus a sibling.

    ``P`` (parent) -> ``C`` (child) -> ``G`` (grandchild), plus ``S`` a
    top-level leaf, so the TUI tree has a multi-level branch and a root leaf
    to exercise expand/collapse and leaf multi-select.
    """
    store_path = tmp_path / "repoTree" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 6,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "P": {
                "title": "Parent",
                "status": "open",
                "priority": "high",
                "tags": [],
                "parent": None,
                "worklogs": [],
            },
            "C": {
                "title": "Child",
                "status": "open",
                "priority": "medium",
                "tags": [],
                "parent": "P",
                "worklogs": [],
            },
            "G": {
                "title": "Grandchild",
                "status": "open",
                "priority": "low",
                "tags": [],
                "parent": "C",
                "worklogs": [],
            },
            "S": {
                "title": "Sibling leaf",
                "status": "open",
                "priority": "low",
                "tags": [],
                "parent": None,
                "worklogs": [],
            },
        },
        "series": {},
    }
    store_path.write_text(json.dumps(data_dict))
    return store_path


@pytest.fixture
def tree_ctx(tree_store_file, env):
    """A DotoContext wired to the parent/child tree store."""
    config = load_config(json_path=tree_store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


class TestTaskTreePrefix:
    """Pure-logic tests for the tree triangle + indent seam."""

    def test_prefix_glyph_reflects_state(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        expanded = TaskList.format_tree_prefix(0, True, True)
        collapsed = TaskList.format_tree_prefix(0, True, False)
        leaf = TaskList.format_tree_prefix(0, False, False)
        assert TaskList.TREE_GLYPH_EXPANDED in expanded
        assert TaskList.TREE_GLYPH_COLLAPSED in collapsed
        # A leaf draws no triangle, just the blank glyph + space.
        assert TaskList.TREE_GLYPH_EXPANDED not in leaf
        assert TaskList.TREE_GLYPH_COLLAPSED not in leaf

    def test_prefix_indents_by_depth(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        d0 = TaskList.format_tree_prefix(0, False, False)
        d2 = TaskList.format_tree_prefix(2, False, False)
        # Deeper rows carry more leading indent (width-stable prefix).
        assert len(d2) == len(d0) + 2 * TaskList.TREE_INDENT

    def test_format_row_applies_tree_prefix_from_treerow(self):
        from doxtr_doto.cli.tui.filtersort import TreeRow
        from doxtr_doto.cli.tui.widgets import TaskList

        row = TreeRow(
            task={"id": "P", "title": "Parent", "status": "open"},
            depth=1,
            has_children=True,
            expanded=True,
        )
        cells = TaskList.format_row(row)
        expected_prefix = TaskList.format_tree_prefix(1, True, True)
        assert cells[6].startswith(expected_prefix)
        assert "Parent" in cells[6]

    def test_format_row_treats_bare_dict_as_leaf(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        cells = TaskList.format_row({"id": "x", "title": "T", "status": "open"})
        assert cells[6] == TaskList.format_tree_prefix(0, False, False) + "T"

    def test_format_tree_prefix_is_overridable(self):
        from doxtr_doto.cli.tui.widgets import TaskList

        class ThemedTaskList(TaskList):
            TREE_GLYPH_EXPANDED = "v"
            TREE_GLYPH_COLLAPSED = ">"
            TREE_INDENT = 4

        assert "v" in ThemedTaskList.format_tree_prefix(0, True, True)
        assert ">" in ThemedTaskList.format_tree_prefix(0, True, False)
        # The subclass's wider indent flows through format_row's Title cell.
        row = ThemedTaskList.format_row({"id": "x", "title": "T", "status": "open"})
        # Leaf at depth 0 with the base glyphs is unchanged, but a themed
        # parent prefix uses the overridden glyph.
        from doxtr_doto.cli.tui.filtersort import TreeRow

        parent_row = ThemedTaskList.format_row(
            TreeRow(
                task={"id": "p", "title": "P", "status": "open"},
                depth=1,
                has_children=True,
                expanded=False,
            )
        )
        assert "    " in parent_row[6]  # 4-space indent at depth 1
        assert ">" in parent_row[6]
        assert row[6].endswith("T")

    def test_list_view_format_line_applies_tree_prefix(self):
        from doxtr_doto.cli.tui.filtersort import TreeRow
        from doxtr_doto.cli.tui.widgets import ListView

        row = TreeRow(
            task={"id": "C", "title": "Child", "status": "open"},
            depth=2,
            has_children=False,
            expanded=False,
        )
        line = ListView.format_line(row, highlighted=False)
        assert ListView.format_tree_prefix(2, False, False) in line
        assert "Child" in line


class TestTaskTreeInteraction:
    """Pilot-driven tests of the expandable task tree + Space semantics."""

    def _app(self, ctx):
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL
        return app

    def test_tree_rebuilds_nested_rows_expanded_by_default(self, tree_ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(tree_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Parents default EXPANDED: the whole branch is visible.
                assert set(table.row_ids) == {"P", "C", "G", "S"}
                # P and C have children; G and S are leaves.
                hc = dict(zip(table.row_ids, table.row_has_children, strict=True))
                assert hc["P"] is True
                assert hc["C"] is True
                assert hc["G"] is False
                assert hc["S"] is False

        _run(body())

    def test_space_on_parent_collapses_and_expands_children(self, tree_ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(tree_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Cursor starts on P (a parent). Space collapses its subtree.
                assert table.selected_id() == "P"
                await pilot.press("space")
                await pilot.pause()
                assert "P" in app._collapsed_ids
                # C and G disappear; P and the sibling S remain.
                assert set(table.row_ids) == {"P", "S"}
                # Space again re-expands.
                await pilot.press("space")
                await pilot.pause()
                assert "P" not in app._collapsed_ids
                assert set(table.row_ids) == {"P", "C", "G", "S"}

        _run(body())

    def test_space_collapse_is_recursive_per_level(self, tree_ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(tree_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Move to C (the mid-level parent) and collapse just its child.
                table.select_id("C")
                await pilot.pause()
                assert table.selected_id() == "C"
                await pilot.press("space")
                await pilot.pause()
                # Only G (under C) is hidden; P, C, S remain.
                assert set(table.row_ids) == {"P", "C", "S"}

        _run(body())

    def test_space_on_leaf_toggles_multi_select(self, tree_ctx):
        from doxtr_doto.cli.tui.widgets import TaskList

        app = self._app(tree_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                # Move cursor to the leaf S and Space-select it.
                table.select_id("S")
                await pilot.pause()
                assert table.selected_id() == "S"
                await pilot.press("space")
                await pilot.pause()
                # Leaf Space is still the multi-select toggle (not expansion).
                assert table.selected_ids == {"S"}
                assert app._collapsed_ids == set()
                await pilot.press("space")
                await pilot.pause()
                assert table.selected_ids == set()

        _run(body())


class TestListViewTreeInteraction:
    """Render-only tests of the expandable task tree in the LIST layout.

    Space is a TABLE-only affordance, so the LIST layout exercises the tree by
    passing a ``collapsed_ids`` set straight to :meth:`ListView.rebuild` and
    asserting the rendered rows - mirroring :class:`TestTaskTreeInteraction`
    for the table, but render-only.
    """

    @staticmethod
    def _tree_tasks():
        return [
            {"id": "P", "title": "Parent", "status": "open", "parent": None},
            {"id": "C", "title": "Child", "status": "open", "parent": "P"},
            {"id": "G", "title": "Grandchild", "status": "open", "parent": "C"},
            {"id": "S", "title": "Sibling leaf", "status": "open", "parent": None},
        ]

    def test_list_view_rebuilds_nested_rows_expanded_by_default(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        view.rebuild(self._tree_tasks())
        # Parents default EXPANDED: the whole branch is visible, in order.
        assert view.row_ids == ["P", "C", "G", "S"]

    def test_list_view_renders_indented_triangle_rows(self):
        from doxtr_doto.cli.tui.filtersort import flatten_tree
        from doxtr_doto.cli.tui.widgets import ListView

        tasks = self._tree_tasks()
        rows = flatten_tree(tasks)
        by_id = {r.task["id"]: ListView.format_line(r, highlighted=False) for r in rows}
        # Parent P (expanded, depth 0): expanded triangle, no indent.
        assert ListView.TREE_GLYPH_EXPANDED in by_id["P"]
        assert ListView.format_tree_prefix(0, True, True) in by_id["P"]
        # Child C (expanded parent, depth 1): one indent level + triangle.
        assert ListView.format_tree_prefix(1, True, True) in by_id["C"]
        # Grandchild G (leaf, depth 2): two indent levels, leaf blank glyph.
        assert ListView.format_tree_prefix(2, False, False) in by_id["G"]
        assert ListView.TREE_GLYPH_EXPANDED not in by_id["G"]
        assert ListView.TREE_GLYPH_COLLAPSED not in by_id["G"]
        # Sibling leaf S (depth 0 leaf).
        assert ListView.format_tree_prefix(0, False, False) in by_id["S"]

    def test_list_view_collapsed_parent_hides_descendants(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        # Collapse P directly via the rebuild collapsed_ids arg (render-only,
        # since Space is TABLE-only): its descendants C and G vanish.
        view.rebuild(self._tree_tasks(), {"P"})
        assert view.row_ids == ["P", "S"]

    def test_list_view_mid_level_collapse_hides_only_that_subtree(self):
        from doxtr_doto.cli.tui.widgets import ListView

        view = ListView()
        # Collapse only C: its child G is hidden, but P, C, and S remain.
        view.rebuild(self._tree_tasks(), {"C"})
        assert view.row_ids == ["P", "C", "S"]
