"""Tests for the configurable TUI add-task modal (Feature: add-task fields).

Covers the pure, render-independent logic in
:mod:`doxtr_doto.cli.tui.add_fields` (preset resolution, explicit-list
override + ordering, dynamic ``all`` derivation, per-field default resolution)
and the :class:`doxtr_doto.cli.tui.app.AddTaskScreen` wiring (field build,
result collection, backward-compatible minimal behavior).

The pure helpers are tested directly; the modal-rendering behaviors use the
Textual :class:`~textual.pilot.Pilot` the same way :mod:`tests.test_tui_time_view`
does.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

from doxtr_doto.cli.config import DotoConfig
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import OutputFormatter
from doxtr_doto.cli.repo_registry import DiscoveredRepo
from doxtr_doto.cli.tui import add_fields
from doxtr_doto.cli.tui.app import AddTaskResult, AddTaskScreen
from doxtr_doto.fields import TASK_FIELDS

# --- Pure preset/field resolution ----------------------------------------


def test_minimal_preset_is_title_only() -> None:
    assert add_fields.resolve_field_names("minimal") == ("title",)
    # Unset / None falls back to minimal (backward compatible).
    assert add_fields.resolve_field_names(None) == ("title",)
    assert add_fields.resolve_field_names("") == ("title",)


def test_default_preset_order() -> None:
    assert add_fields.resolve_field_names("default") == (
        "title",
        "tags",
        "due",
        "assignee",
        "body",
    )


def test_all_preset_derives_from_registry_and_excludes_computed() -> None:
    names = add_fields.resolve_field_names("all")
    # created/updated are computed and must be excluded.
    assert "created" not in names
    assert "updated" not in names
    # Every other registry field (in registry order) is present.
    expected = tuple(f.name for f in TASK_FIELDS if f.name not in {"created", "updated"})
    assert names == expected
    # Spot-check the required settable fields are all there.
    for required in (
        "title",
        "assignee",
        "priority",
        "status",
        "due",
        "estimate",
        "tags",
        "depends_on",
        "body",
        "progress",
        "raci",
    ):
        assert required in names


def test_all_preset_includes_newly_registered_field(monkeypatch) -> None:
    """A field added to TASK_FIELDS auto-appears in the ``all`` preset."""
    from doxtr_doto.fields import FieldDefinition

    new_field = FieldDefinition(
        name="severity",
        rst_name="severity",
        json_name="severity",
        display_label="Severity",
    )
    extended = (*TASK_FIELDS, new_field)
    monkeypatch.setattr(add_fields, "TASK_FIELDS", extended)
    monkeypatch.setattr(add_fields, "BY_NAME", {f.name: f for f in extended})
    names = add_fields.resolve_field_names("all")
    assert "severity" in names


def test_unknown_preset_falls_back_to_minimal() -> None:
    assert add_fields.resolve_field_names("bogus") == ("title",)


def test_explicit_list_overrides_preset_and_preserves_order() -> None:
    names = add_fields.resolve_field_names(["due", "assignee", "tags"])
    # title is always prepended when omitted.
    assert names == ("title", "due", "assignee", "tags")


def test_explicit_list_keeps_title_position_when_present() -> None:
    names = add_fields.resolve_field_names(["title", "body", "due"])
    assert names == ("title", "body", "due")


def test_explicit_list_drops_unknown_and_computed_fields() -> None:
    names = add_fields.resolve_field_names(["title", "nonsense", "created", "updated", "due"])
    assert names == ("title", "due")


def test_explicit_list_dedupes() -> None:
    names = add_fields.resolve_field_names(["title", "due", "due", "assignee"])
    assert names == ("title", "due", "assignee")


# --- The ``repo`` pseudo-field in an explicit list -------------------------


def test_explicit_list_keeps_repo_first() -> None:
    """``repo`` listed first stays at index 0 (title already present)."""
    names = add_fields.resolve_field_names(["repo", "title", "body"])
    assert names == ("repo", "title", "body")


def test_explicit_list_repo_first_without_title_prepends_title() -> None:
    """Title is prepended at index 0, pushing an explicitly-first repo to 1."""
    names = add_fields.resolve_field_names(["repo", "body"])
    assert names == ("title", "repo", "body")


def test_explicit_list_repo_keeps_last_position() -> None:
    names = add_fields.resolve_field_names(["title", "due", "repo"])
    assert names == ("title", "due", "repo")


def test_explicit_list_dedupes_repo() -> None:
    names = add_fields.resolve_field_names(["repo", "title", "repo"])
    assert names == ("repo", "title")


def test_explicit_list_keeps_repo_alongside_dropped_unknown() -> None:
    """An unknown non-repo name is still dropped while ``repo`` is kept."""
    names = add_fields.resolve_field_names(["repo", "title", "nonsense", "due"])
    assert names == ("repo", "title", "due")


def test_presets_never_contain_repo() -> None:
    """Presets (and None) keep the implicit after-title placement: no ``repo``."""
    for spec in ("minimal", "default", "all", None):
        assert add_fields.REPO_FIELD not in add_fields.resolve_field_names(spec)


# --- Per-field default resolution -----------------------------------------


def test_static_defaults_prefill() -> None:
    config = DotoConfig()
    defaults = {"assignee": "alice", "priority": "high", "tags": "frontend, urgent"}
    assert add_fields.resolve_default("assignee", defaults, config) == "alice"
    assert add_fields.resolve_default("priority", defaults, config) == "high"
    assert add_fields.resolve_default("tags", defaults, config) == "frontend, urgent"


def test_relative_due_default_resolves_to_concrete_date() -> None:
    config = DotoConfig()
    resolved = add_fields.resolve_default("due", {"due": "tomorrow"}, config)
    assert resolved == (date.today() + timedelta(days=1)).isoformat()


def test_relative_due_plus_days() -> None:
    config = DotoConfig()
    resolved = add_fields.resolve_default("due", {"due": "+7d"}, config)
    assert resolved == (date.today() + timedelta(days=7)).isoformat()


def test_unparseable_due_default_falls_back_to_empty() -> None:
    config = DotoConfig()
    assert add_fields.resolve_default("due", {"due": "not-a-date"}, config) == ""


def test_config_default_assignee_is_fallback() -> None:
    config = DotoConfig(default_assignee="bob")
    # No tui_add_defaults entry -> classic config default is used.
    assert add_fields.resolve_default("assignee", {}, config) == "bob"


def test_config_default_priority_status_fallbacks() -> None:
    config = DotoConfig(default_priority="low", default_status="open")
    assert add_fields.resolve_default("priority", {}, config) == "low"
    assert add_fields.resolve_default("status", {}, config) == "open"


def test_tui_add_defaults_overrides_config_default_assignee() -> None:
    config = DotoConfig(default_assignee="bob")
    assert add_fields.resolve_default("assignee", {"assignee": "carol"}, config) == "carol"


def test_empty_default_for_unconfigured_field() -> None:
    config = DotoConfig()
    assert add_fields.resolve_default("body", {}, config) == ""
    assert add_fields.resolve_default("depends_on", {}, config) == ""


# --- Config plumbing ------------------------------------------------------


def test_config_applies_tui_add_fields_string() -> None:
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_add_fields": "all"})
    assert config.tui_add_fields == "all"


def test_config_applies_tui_add_fields_list() -> None:
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_add_fields": ["title", "due"]})
    assert config.tui_add_fields == ["title", "due"]


def test_config_applies_tui_add_defaults_table() -> None:
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_add_defaults": {"assignee": "alice", "due": "tomorrow"}})
    assert config.tui_add_defaults == {"assignee": "alice", "due": "tomorrow"}


def test_config_default_is_minimal_with_empty_defaults() -> None:
    config = DotoConfig()
    assert config.tui_add_fields == "minimal"
    assert config.tui_add_defaults == {}


def test_config_auto_select_new_task_defaults_true() -> None:
    """The new option defaults to on (auto-select freshly added tasks)."""
    assert DotoConfig().tui_auto_select_new_task is True


def test_config_applies_tui_auto_select_new_task_false() -> None:
    """An explicit false in the ``[doto]`` table opts out of auto-select."""
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_auto_select_new_task": False})
    assert config.tui_auto_select_new_task is False


def test_config_applies_tui_auto_select_new_task_true() -> None:
    """An explicit true is honored (and coerced to a bool)."""
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig(tui_auto_select_new_task=False)
    _apply_toml_config(config, {"tui_auto_select_new_task": True})
    assert config.tui_auto_select_new_task is True


def test_config_recent_done_days_defaults_to_ten() -> None:
    """The recent-done window defaults to 10 days."""
    assert DotoConfig().tui_recent_done_days == 10


def test_config_applies_tui_recent_done_days_override() -> None:
    """An explicit ``tui_recent_done_days`` in ``[doto]`` overrides the default."""
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_recent_done_days": 30})
    assert config.tui_recent_done_days == 30


def test_config_coerces_tui_recent_done_days_to_int() -> None:
    """A string/float day count is coerced to an int."""
    from doxtr_doto.cli.config import _apply_toml_config

    config = DotoConfig()
    _apply_toml_config(config, {"tui_recent_done_days": "7"})
    assert config.tui_recent_done_days == 7


# --- Screen-level pure logic ----------------------------------------------


def _repo(tmp_path: Path, name: str = "repo") -> DiscoveredRepo:
    return DiscoveredRepo(name=name, path=str(tmp_path))


def test_screen_resolve_fields_uses_config(tmp_path) -> None:
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields="default")
    screen = AddTaskScreen([repo], repo, config=config)
    assert screen.resolve_fields() == ("title", "tags", "due", "assignee", "body")


def test_screen_resolve_fields_minimal_without_config(tmp_path) -> None:
    repo = _repo(tmp_path)
    screen = AddTaskScreen([repo], repo)
    assert screen.resolve_fields() == ("title",)


def test_screen_build_fields_resolves_defaults(tmp_path) -> None:
    repo = _repo(tmp_path)
    config = DotoConfig(
        tui_add_fields=["title", "assignee", "due"],
        tui_add_defaults={"assignee": "alice", "due": "tomorrow"},
    )
    screen = AddTaskScreen([repo], repo, config=config)
    fields = screen.build_fields()
    assert fields["title"] == ""
    assert fields["assignee"] == "alice"
    assert fields["due"] == (date.today() + timedelta(days=1)).isoformat()


def test_screen_build_fields_expands_raci(tmp_path) -> None:
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields=["title", "raci"])
    screen = AddTaskScreen([repo], repo, config=config)
    fields = screen.build_fields()
    for role in ("responsible", "accountable", "consulted", "informed"):
        assert fields[f"raci_{role}"] == ""


def test_screen_default_repo_value_matches_by_name(tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    current = DiscoveredRepo(name="current", path=str(tmp_path))
    repo_b = DiscoveredRepo(name="myrepo", path=str(other))
    config = DotoConfig(tui_add_defaults={"repo": "MyRepo"})
    screen = AddTaskScreen([current, repo_b], current, config=config)
    assert screen.default_repo_value() == str(other)


def test_screen_default_repo_value_unknown_falls_back_to_current(tmp_path) -> None:
    current = DiscoveredRepo(name="current", path=str(tmp_path))
    config = DotoConfig(tui_add_defaults={"repo": "does-not-exist"})
    screen = AddTaskScreen([current], current, config=config)
    assert screen.default_repo_value() == str(tmp_path)


def test_screen_default_repo_value_no_default_is_current(tmp_path) -> None:
    current = DiscoveredRepo(name="current", path=str(tmp_path))
    screen = AddTaskScreen([current], current, config=DotoConfig())
    assert screen.default_repo_value() == str(tmp_path)


# --- Pilot-driven modal behavior ------------------------------------------


def _make_ctx(tmp_path: Path, config: DotoConfig | None = None) -> DotoContext:
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    global_store = GlobalStateStore(tmp_path / "global.json")
    # Suppress the once-per-day kickstart nudge so it doesn't intercept keys.
    from doxtr_doto.cli.tui import nudge

    state = global_store.load()
    state.last_prompt_date = nudge.today_iso()
    global_store.save(state)
    cfg = config or DotoConfig()
    cfg.source_dir = tmp_path
    cfg.json_file = Path(".doto/tasks.json")
    return DotoContext(
        config=cfg,
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )


def test_minimal_modal_collects_title_only(tmp_path) -> None:
    """Backward compat: minimal modal exposes only the title and returns it."""
    repo = _repo(tmp_path)
    config = DotoConfig()  # default "minimal"
    screen = AddTaskScreen([repo], repo, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Only the title input and its label exist (no Save button).
            screen.query_one("#add-input")
            assert not screen.query("#add-save")
            screen.query_one("#add-input").value = "hello world"
            screen._submit()
            await pilot.pause()

        assert collected and collected[0] is not None
        assert collected[0].title == "hello world"
        assert collected[0].repo.path == repo.path
        assert collected[0].assignee is None
        assert collected[0].body is None

    asyncio.run(scenario())


def test_full_modal_collects_all_values(tmp_path) -> None:
    """The multi-field layout maps widget values to the right result fields."""
    repo = _repo(tmp_path)
    config = DotoConfig(
        tui_add_fields=["title", "assignee", "tags", "due", "body"],
        statuses=["open", "done"],
        priorities=["low", "high"],
    )
    screen = AddTaskScreen(
        [repo],
        repo,
        config=config,
        statuses=config.statuses,
        priorities=config.priorities,
    )

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Multi-field layout: a Save button and per-field inputs exist.
            screen.query_one("#add-save")
            screen.query_one("#add-title").value = "full task"
            screen.query_one("#add-assignee").value = "alice"
            screen.query_one("#add-tags").value = "a, b"
            screen.query_one("#add-due").value = "2030-01-15"
            screen.query_one("#add-body").text = "the body"
            screen._submit()
            await pilot.pause()

        assert collected and collected[0] is not None
        result = collected[0]
        assert result.title == "full task"
        assert result.assignee == "alice"
        assert result.tags == "a, b"
        assert result.due == "2030-01-15"
        assert result.body == "the body"
        # Fields not in the configured list stay None.
        assert result.priority is None
        assert result.status is None
        assert result.estimate is None
        assert result.raci is None

    asyncio.run(scenario())


def test_full_modal_invalid_due_keeps_modal_open(tmp_path) -> None:
    """An unparseable due at submit surfaces an error and keeps the modal open."""
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields=["title", "due"])
    screen = AddTaskScreen([repo], repo, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.query_one("#add-title").value = "t"
            screen.query_one("#add-due").value = "not-a-date"
            screen._submit()
            await pilot.pause()
            # Still mounted (not dismissed) because the due is invalid.
            assert screen.is_running

        assert collected == []

    asyncio.run(scenario())


def test_full_modal_empty_title_cancels(tmp_path) -> None:
    """Submitting with an empty title dismisses with None (cancel)."""
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields=["title", "assignee"])
    screen = AddTaskScreen([repo], repo, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.query_one("#add-assignee").value = "alice"
            screen._submit()
            await pilot.pause()

        assert collected == [None]

    asyncio.run(scenario())


def test_parse_progress_valid_and_invalid() -> None:
    """parse_progress returns an int for valid 0-100 and raises otherwise."""
    import pytest

    assert AddTaskScreen.parse_progress("") is None
    assert AddTaskScreen.parse_progress("  ") is None
    assert AddTaskScreen.parse_progress("0") == 0
    assert AddTaskScreen.parse_progress("50") == 50
    assert AddTaskScreen.parse_progress("100") == 100
    # Non-numeric is rejected (kept out of the store so render never crashes).
    with pytest.raises(ValueError, match="whole number"):
        AddTaskScreen.parse_progress("soon")
    # Out-of-range is rejected.
    with pytest.raises(ValueError, match="between 0 and 100"):
        AddTaskScreen.parse_progress("150")
    with pytest.raises(ValueError, match="between 0 and 100"):
        AddTaskScreen.parse_progress("-5")


def test_full_modal_all_fields_map_to_typed_result(tmp_path) -> None:
    """The ``all`` layout maps every entered value to the right field/type."""
    repo = _repo(tmp_path)
    config = DotoConfig(
        tui_add_fields="all",
        statuses=["open", "done"],
        priorities=["low", "high"],
    )
    screen = AddTaskScreen(
        [repo],
        repo,
        config=config,
        statuses=config.statuses,
        priorities=config.priorities,
    )

    async def scenario() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Select

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.query_one("#add-title").value = "big task"
            screen.query_one("#add-assignee").value = "alice"
            screen.query_one("#add-priority", Select).value = "high"
            screen.query_one("#add-status", Select).value = "open"
            screen.query_one("#add-due").value = "2030-01-15"
            screen.query_one("#add-estimate").value = "90m"
            screen.query_one("#add-tags").value = "a, b"
            screen.query_one("#add-depends_on").value = "T-1, T-2"
            screen.query_one("#add-progress").value = "40"
            screen.query_one("#add-raci-responsible").value = "alice, bob"
            screen.query_one("#add-raci-accountable").value = "carol"
            screen._submit()
            await pilot.pause()

        assert collected and collected[0] is not None
        result = collected[0]
        assert result.title == "big task"
        assert result.assignee == "alice"
        assert result.priority == "high"
        assert result.status == "open"
        assert result.due == "2030-01-15"
        assert result.estimate == 90
        assert isinstance(result.estimate, int)
        assert result.tags == "a, b"
        assert result.depends_on == "T-1, T-2"
        assert result.progress == 40
        assert isinstance(result.progress, int)
        assert result.raci == "responsible alice, bob, accountable carol"

    asyncio.run(scenario())


def test_full_modal_invalid_progress_keeps_modal_open(tmp_path) -> None:
    """A non-numeric progress at submit keeps the modal open (no corrupt store)."""
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields=["title", "progress"])
    screen = AddTaskScreen([repo], repo, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.query_one("#add-title").value = "t"
            screen.query_one("#add-progress").value = "soon"
            screen._submit()
            await pilot.pause()
            assert screen.is_running

        assert collected == []

    asyncio.run(scenario())


def test_select_blank_fallback_for_bogus_default(tmp_path) -> None:
    """A valid select default is pre-selected; a bogus one falls back to BLANK."""
    from textual.widgets import Select

    repo = _repo(tmp_path)
    config = DotoConfig(
        tui_add_fields=["title", "priority", "status"],
        statuses=["open", "done"],
        priorities=["low", "high"],
        tui_add_defaults={"priority": "high", "status": "bogus"},
    )
    screen = AddTaskScreen(
        [repo],
        repo,
        config=config,
        statuses=config.statuses,
        priorities=config.priorities,
    )

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert screen.query_one("#add-priority", Select).value == "high"
            # The bogus status default is not a valid choice -> no selection.
            status_value = screen.query_one("#add-status", Select).value
            assert status_value not in ("open", "done", "bogus")
            assert not isinstance(status_value, str)

    asyncio.run(scenario())


def test_new_field_renders_but_is_not_collected(monkeypatch, tmp_path) -> None:
    """Pins the BLOCKER-4b boundary: a newly registered field renders in the
    ``all`` preset and gets a widget, but its value is intentionally NOT
    carried through ``collect_result`` (not representable in AddTaskResult)."""
    from textual.widgets import Input

    from doxtr_doto.fields import FieldDefinition

    new_field = FieldDefinition(
        name="severity",
        rst_name="severity",
        json_name="severity",
        display_label="Severity",
    )
    extended = (*TASK_FIELDS, new_field)
    monkeypatch.setattr(add_fields, "TASK_FIELDS", extended)
    monkeypatch.setattr(add_fields, "BY_NAME", {f.name: f for f in extended})
    # app._build_field reads BY_NAME for the fallback label too.
    import doxtr_doto.cli.tui.app as app_mod

    monkeypatch.setattr(app_mod, "BY_NAME", {f.name: f for f in extended})

    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields="all")
    screen = AddTaskScreen([repo], repo, config=config)
    # The new field is surfaced in the resolved field list.
    assert "severity" in screen.resolve_fields()

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            # It renders as a plain input (default kind).
            severity_input = screen.query_one("#add-severity", Input)
            severity_input.value = "high"
            screen.query_one("#add-title").value = "t"
            screen._submit()
            await pilot.pause()

        assert collected and collected[0] is not None
        result = collected[0]
        # The value was entered but is intentionally not persisted (no
        # AddTaskResult field for it) - the documented new-field boundary.
        assert not hasattr(result, "severity")
        assert result.title == "t"

    asyncio.run(scenario())


def test_actions_add_task_stores_typed_fields(tmp_path, monkeypatch) -> None:
    """Non-UI: add_task stores correct types and remembers new names."""
    from doxtr_doto.cli import known_names
    from doxtr_doto.cli.tui import actions

    ctx = _make_ctx(tmp_path)
    # known_names.remember_task_names resolves its path via load_config() from
    # the cwd, so run from tmp_path to keep the memory store next to the store.
    monkeypatch.chdir(tmp_path)
    task_id = actions.add_task(
        ctx,
        "typed task",
        assignee="dave",
        tags="x, y",
        due="2030-02-01",
        estimate=120,
        depends_on="T-9, T-10",
        body="desc",
        progress=75,
        raci="responsible dave, consulted erin",
    )
    stored = ctx.store.get_task(task_id)
    assert stored is not None
    assert stored["title"] == "typed task"
    assert stored["assignee"] == "dave"
    assert stored["tags"] == ["x", "y"]
    assert stored["due"] == "2030-02-01"
    assert stored["estimate"] == 120
    assert isinstance(stored["estimate"], int)
    assert stored["depends_on"] == ["T-9", "T-10"]
    assert stored["body"] == "desc"
    assert stored["progress"] == 75
    assert isinstance(stored["progress"], int)
    assert stored["raci"] == {
        "responsible": ["dave"],
        "consulted": ["erin"],
    }
    # New assignee/tags are remembered in the known-names memory store.
    path = ctx.config.get_json_path().parent / "known_names.json"
    assert "dave" in known_names.get_assignees(path=path)
    remembered_tags = known_names.get_tags(path=path)
    assert "x" in remembered_tags
    assert "y" in remembered_tags


def test_field_kind_builders_dispatch_is_data_driven(tmp_path) -> None:
    """A new render kind is addable via one method + one table entry."""
    repo = _repo(tmp_path)

    class _Themed(AddTaskScreen):
        FIELD_KINDS = {**AddTaskScreen.FIELD_KINDS, "title": "banner"}
        FIELD_KIND_BUILDERS = {**AddTaskScreen.FIELD_KIND_BUILDERS, "banner": "_build_banner"}
        built: list[str] = []

        def _build_banner(self, name, label, fields):
            type(self).built.append(name)
            return self._build_input(name, label, fields)

    config = DotoConfig(tui_add_fields=["title", "assignee"])
    screen = _Themed([repo], repo, config=config)
    # Exercise the dispatch directly (pure, no rendering needed).
    screen._build_field("title", {"title": ""})
    assert _Themed.built == ["title"]
    # The default kind still routes to the input builder for other fields.
    widgets = screen._build_field("assignee", {"assignee": ""})
    assert any(w.id == "add-assignee" for w in widgets if hasattr(w, "id"))


def test_field_suggester_seam_routes_by_name(tmp_path) -> None:
    """field_suggester dispatches tags/assignee and None for others."""
    from doxtr_doto.cli.tui.app import TagSuggester

    repo = _repo(tmp_path)
    screen = AddTaskScreen(
        [repo],
        repo,
        config=DotoConfig(),
        known_assignees=["alice"],
        known_tags=["frontend"],
    )
    assert isinstance(screen.field_suggester("tags"), TagSuggester)
    assert screen.field_suggester("assignee") is not None
    assert screen.field_suggester("due") is None
    assert screen.field_suggester("title") is None


def test_select_choices_seam(tmp_path) -> None:
    """select_choices maps priority->priorities and others->statuses."""
    repo = _repo(tmp_path)
    screen = AddTaskScreen(
        [repo],
        repo,
        config=DotoConfig(),
        statuses=["open", "done"],
        priorities=["low", "high"],
    )
    assert screen.select_choices("priority") == ["low", "high"]
    assert screen.select_choices("status") == ["open", "done"]


# --- Positioning the repo selector via an explicit ``repo`` entry ----------


def _two_repos(tmp_path: Path) -> tuple[DiscoveredRepo, DiscoveredRepo]:
    """Return a current repo and a second repo so the selector renders."""
    other = tmp_path / "other"
    other.mkdir()
    current = DiscoveredRepo(name="current", path=str(tmp_path))
    second = DiscoveredRepo(name="second", path=str(other))
    return current, second


def test_repo_renders_at_listed_position_before_title(tmp_path) -> None:
    """With >1 repo and ``repo`` first, the selector precedes the title widget
    in DOM order and ``_selected_repo`` still resolves."""
    current, second = _two_repos(tmp_path)
    config = DotoConfig(tui_add_fields=["repo", "title", "due"])
    screen = AddTaskScreen([current, second], current, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Input, Select

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            repo_sel = screen.query_one("#add-repo", Select)
            title_input = screen.query_one("#add-title", Input)
            # DOM order: the whole modal's widgets, in document order.
            ordered = list(screen.query("*").results())
            assert ordered.index(repo_sel) < ordered.index(title_input)
            # The selector still resolves the chosen repo.
            assert screen._selected_repo().path == current.path

    asyncio.run(scenario())


def test_repo_in_list_not_also_injected_after_title(tmp_path) -> None:
    """When ``repo`` is explicitly placed last, the selector is NOT also
    injected after the title (exactly one ``#add-repo`` exists, at the end)."""
    current, second = _two_repos(tmp_path)
    config = DotoConfig(tui_add_fields=["title", "due", "repo"])
    screen = AddTaskScreen([current, second], current, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Input, Select

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            selectors = list(screen.query("#add-repo").results())
            assert len(selectors) == 1
            repo_sel = screen.query_one("#add-repo", Select)
            title_input = screen.query_one("#add-title", Input)
            ordered = list(screen.query("*").results())
            # Explicitly last: the selector follows the title in DOM order.
            assert ordered.index(title_input) < ordered.index(repo_sel)

    asyncio.run(scenario())


def test_preset_repo_selector_still_after_title(tmp_path) -> None:
    """A preset keeps the implicit after-title placement (unchanged behavior)."""
    current, second = _two_repos(tmp_path)
    config = DotoConfig(tui_add_fields="default")
    screen = AddTaskScreen([current, second], current, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Input, Select

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            repo_sel = screen.query_one("#add-repo", Select)
            title_input = screen.query_one("#add-title", Input)
            tags_input = screen.query_one("#add-tags", Input)
            ordered = list(screen.query("*").results())
            # Selector sits right after the title and before the next field.
            assert ordered.index(title_input) < ordered.index(repo_sel)
            assert ordered.index(repo_sel) < ordered.index(tags_input)

    asyncio.run(scenario())


def test_repo_in_list_single_repo_renders_no_selector(tmp_path) -> None:
    """With a single repo, ``repo`` in the list renders no selector and the
    modal still composes without crashing."""
    repo = _repo(tmp_path)
    config = DotoConfig(tui_add_fields=["repo", "title", "due"])
    screen = AddTaskScreen([repo], repo, config=config)

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            # No selector is rendered when there is at most one repo.
            assert not screen.query("#add-repo")
            # The title field still renders.
            screen.query_one("#add-title")

    asyncio.run(scenario())


def test_repo_in_list_build_and_collect_no_keyerror(tmp_path) -> None:
    """``build_fields``/``collect_result`` must not KeyError on a ``repo``
    entry: it is the selector pseudo-field, skipped by both."""
    current, second = _two_repos(tmp_path)
    config = DotoConfig(tui_add_fields=["repo", "title", "assignee"])
    screen = AddTaskScreen([current, second], current, config=config)
    # build_fields skips the repo pseudo-field (no text default).
    fields = screen.build_fields()
    assert "repo" not in fields
    assert set(fields) == {"title", "assignee"}

    async def scenario() -> None:
        from textual.app import App, ComposeResult

        collected: list[AddTaskResult | None] = []

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                return iter(())

            def on_mount(self) -> None:
                self.push_screen(screen, collected.append)

        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.query_one("#add-title").value = "t"
            screen.query_one("#add-assignee").value = "alice"
            # collect_result must not raise and must carry the selected repo.
            screen._submit()
            await pilot.pause()

        assert collected and collected[0] is not None
        assert collected[0].title == "t"
        assert collected[0].assignee == "alice"
        assert collected[0].repo.path == current.path

    asyncio.run(scenario())
