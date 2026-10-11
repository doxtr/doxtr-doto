"""Tests for the RACI module and RACI integration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from doxtr_doto.raci import (
    format_raci,
    merge_raci,
    parse_raci,
    raci_names,
    render_raci_compact,
    render_raci_html,
    reset_raci_html_renderer,
)

# ── parse_raci ──────────────────────────────────────────────────────────────


class TestParseRaci:
    """Tests for the parse_raci function."""

    def test_empty_string(self) -> None:
        assert parse_raci("") == {}

    def test_whitespace_only(self) -> None:
        assert parse_raci("   ") == {}

    def test_single_role(self) -> None:
        result = parse_raci("responsible alice")
        assert result == {"responsible": ["alice"]}

    def test_all_roles(self) -> None:
        result = parse_raci("responsible alice, accountable bob, consulted carol, informed dave")
        assert result == {
            "responsible": ["alice"],
            "accountable": ["bob"],
            "consulted": ["carol"],
            "informed": ["dave"],
        }

    def test_abbreviations(self) -> None:
        result = parse_raci("r alice, a bob, c carol, i dave")
        assert result == {
            "responsible": ["alice"],
            "accountable": ["bob"],
            "consulted": ["carol"],
            "informed": ["dave"],
        }

    def test_multiple_people_per_role(self) -> None:
        result = parse_raci("responsible alice, responsible bob")
        assert result == {"responsible": ["alice", "bob"]}

    def test_case_insensitive_roles(self) -> None:
        result = parse_raci("Responsible Alice, ACCOUNTABLE Bob")
        assert result == {
            "responsible": ["Alice"],
            "accountable": ["Bob"],
        }

    def test_deduplicates_names(self) -> None:
        result = parse_raci("responsible alice, responsible alice")
        assert result == {"responsible": ["alice"]}

    def test_extra_whitespace(self) -> None:
        result = parse_raci("  responsible   alice  ,  accountable   bob  ")
        assert result == {
            "responsible": ["alice"],
            "accountable": ["bob"],
        }

    def test_invalid_role_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown RACI role"):
            parse_raci("owner alice")

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 'role name'"):
            parse_raci("responsible")

    def test_empty_segments_ignored(self) -> None:
        result = parse_raci("responsible alice,,accountable bob,")
        assert result == {
            "responsible": ["alice"],
            "accountable": ["bob"],
        }


# ── format_raci ─────────────────────────────────────────────────────────────


class TestFormatRaci:
    """Tests for the format_raci function."""

    def test_none(self) -> None:
        assert format_raci(None) == ""

    def test_empty_dict(self) -> None:
        assert format_raci({}) == ""

    def test_single_role(self) -> None:
        assert format_raci({"responsible": ["alice"]}) == "responsible alice"

    def test_all_roles(self) -> None:
        raci = {
            "responsible": ["alice"],
            "accountable": ["bob"],
            "consulted": ["carol"],
            "informed": ["dave"],
        }
        result = format_raci(raci)
        assert result == ("responsible alice, accountable bob, consulted carol, informed dave")

    def test_multiple_names(self) -> None:
        raci = {"responsible": ["alice", "bob"]}
        assert format_raci(raci) == "responsible alice, responsible bob"

    def test_order_follows_raci_roles(self) -> None:
        # Even if the dict has keys in different order, output follows R-A-C-I
        raci = {"informed": ["dave"], "responsible": ["alice"]}
        result = format_raci(raci)
        assert result == "responsible alice, informed dave"


# ── round-trip ──────────────────────────────────────────────────────────────


class TestRaciRoundTrip:
    """Test that parse_raci and format_raci are inverses."""

    @pytest.mark.parametrize(
        "raci",
        [
            {"responsible": ["alice"]},
            {
                "responsible": ["alice"],
                "accountable": ["bob"],
                "consulted": ["carol"],
                "informed": ["dave"],
            },
            {"responsible": ["alice", "bob"]},
        ],
    )
    def test_round_trip(self, raci: dict[str, list[str]]) -> None:
        formatted = format_raci(raci)
        parsed = parse_raci(formatted)
        assert parsed == raci


# ── merge_raci ──────────────────────────────────────────────────────────────


class TestMergeRaci:
    """Tests for merge_raci."""

    def test_merge_into_none(self) -> None:
        result = merge_raci(None, {"responsible": ["alice"]})
        assert result == {"responsible": ["alice"]}

    def test_merge_into_existing(self) -> None:
        existing = {"responsible": ["alice"]}
        new = {"consulted": ["carol"]}
        result = merge_raci(existing, new)
        assert result == {"responsible": ["alice"], "consulted": ["carol"]}

    def test_merge_same_role_deduplicates(self) -> None:
        existing = {"responsible": ["alice"]}
        new = {"responsible": ["alice", "bob"]}
        result = merge_raci(existing, new)
        assert result == {"responsible": ["alice", "bob"]}

    def test_existing_preserved(self) -> None:
        existing = {"responsible": ["alice"], "accountable": ["bob"]}
        new = {"consulted": ["carol"]}
        result = merge_raci(existing, new)
        assert "responsible" in result
        assert "accountable" in result
        assert "consulted" in result


# ── render_raci_compact ─────────────────────────────────────────────────────


class TestRenderRaciCompact:
    """Tests for render_raci_compact."""

    def test_none(self) -> None:
        assert render_raci_compact(None) == ""

    def test_empty(self) -> None:
        assert render_raci_compact({}) == ""

    def test_single_role(self) -> None:
        assert render_raci_compact({"responsible": ["alice"]}) == "R: alice"

    def test_multiple_roles(self) -> None:
        raci = {"responsible": ["alice"], "accountable": ["bob"]}
        result = render_raci_compact(raci)
        assert result == "R: alice, A: bob"

    def test_multiple_names(self) -> None:
        raci = {"responsible": ["alice", "bob"]}
        assert render_raci_compact(raci) == "R: alice, bob"


# ── render_raci_html ────────────────────────────────────────────────────────


class TestRenderRaciHtml:
    """Tests for render_raci_html."""

    def test_none_returns_empty(self) -> None:
        reset_raci_html_renderer()
        assert render_raci_html(None) == ""

    def test_basic_rendering(self) -> None:
        reset_raci_html_renderer()
        raci = {"responsible": ["alice"]}
        html = render_raci_html(raci)
        assert "doto-raci" in html
        assert "Responsible" in html
        assert "alice" in html

    def test_escapes_names(self) -> None:
        reset_raci_html_renderer()
        raci = {"responsible": ["<script>alert(1)</script>"]}
        html = render_raci_html(raci)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ── raci_names ──────────────────────────────────────────────────────────────


class TestRaciNames:
    """Tests for raci_names."""

    def test_none(self) -> None:
        assert raci_names(None) == []

    def test_empty(self) -> None:
        assert raci_names({}) == []

    def test_extracts_unique_names(self) -> None:
        raci = {
            "responsible": ["alice"],
            "accountable": ["alice"],
            "consulted": ["bob"],
        }
        names = raci_names(raci)
        assert names == ["alice", "bob"]


# ── DotoTask integration ───────────────────────────────────────────────────


class TestDotoTaskRaci:
    """Tests for RACI on DotoTask."""

    def test_to_dict_includes_raci(self) -> None:
        from doxtr_doto.collectors import DotoTask

        task = DotoTask(
            id="T-1",
            title="Test",
            raci={"responsible": ["alice"], "accountable": ["bob"]},
        )
        d = task.to_dict()
        assert d["raci"] == {"responsible": ["alice"], "accountable": ["bob"]}

    def test_to_dict_raci_none(self) -> None:
        from doxtr_doto.collectors import DotoTask

        task = DotoTask(id="T-1", title="Test")
        d = task.to_dict()
        assert d["raci"] is None

    def test_from_dict_with_raci(self) -> None:
        from doxtr_doto.collectors import DotoTask

        data: dict[str, Any] = {
            "title": "Test",
            "raci": {"responsible": ["alice"]},
        }
        task = DotoTask.from_dict("T-1", data)
        assert task.raci == {"responsible": ["alice"]}

    def test_from_dict_without_raci(self) -> None:
        from doxtr_doto.collectors import DotoTask

        data: dict[str, Any] = {"title": "Test"}
        task = DotoTask.from_dict("T-1", data)
        assert task.raci is None

    def test_to_sync_dict_includes_raci(self) -> None:
        from doxtr_doto.collectors import DotoTask

        task = DotoTask(
            id="T-1",
            title="Test",
            raci={"responsible": ["alice"]},
        )
        d = task.to_sync_dict()
        assert d["raci"] == {"responsible": ["alice"]}


# ── RST directive parsing ──────────────────────────────────────────────────


class TestRaciDirective:
    """Test RACI option in the doto directive via Sphinx build."""

    def test_raci_parsed_from_directive(self, doto_srcdir: Path, make_app: Any) -> None:
        """Test that :raci: option is parsed and stored on the task."""
        tasks_rst = doto_srcdir / "raci_test.rst"
        tasks_rst.write_text(
            """
RACI Test
=========

.. doto:: Task with RACI
   :id: RACI-001
   :raci: responsible alice, accountable bob, consulted carol, informed dave

   A task with RACI roles.
"""
        )

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   raci_test\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        tasks = app.env.doto_data.all_tasks
        assert "RACI-001" in tasks
        task = tasks["RACI-001"]
        assert task.raci is not None
        assert task.raci["responsible"] == ["alice"]
        assert task.raci["accountable"] == ["bob"]
        assert task.raci["consulted"] == ["carol"]
        assert task.raci["informed"] == ["dave"]

    def test_no_raci_is_none(self, doto_srcdir: Path, make_app: Any) -> None:
        """Test that tasks without :raci: have raci=None."""
        tasks_rst = doto_srcdir / "no_raci.rst"
        tasks_rst.write_text(
            """
No RACI Test
============

.. doto:: Task without RACI
   :id: NO-RACI-001

   A task without RACI roles.
"""
        )

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   no_raci\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        tasks = app.env.doto_data.all_tasks
        assert "NO-RACI-001" in tasks
        assert tasks["NO-RACI-001"].raci is None


# ── RST writer round-trip ──────────────────────────────────────────────────


class TestRaciRstWriter:
    """Test RACI in generate_directive_text."""

    def test_raci_emitted(self) -> None:
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {
            "id": "T-1",
            "title": "Test task",
            "raci": {
                "responsible": ["alice"],
                "accountable": ["bob"],
            },
        }
        rst = generate_directive_text(task_data)
        assert ":raci: responsible alice, accountable bob" in rst

    def test_no_raci_not_emitted(self) -> None:
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {"id": "T-1", "title": "Test task"}
        rst = generate_directive_text(task_data)
        assert ":raci:" not in rst


# ── CLI config ──────────────────────────────────────────────────────────────


class TestResolveEnvVars:
    """Tests for resolve_env_vars and resolve_user."""

    def test_simple_var(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"MY_USER": "alice"}):
            assert resolve_env_vars("$MY_USER") == "alice"

    def test_braced_var(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"MY_USER": "alice"}):
            assert resolve_env_vars("${MY_USER}") == "alice"

    def test_missing_var_empty(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {}, clear=True):
            assert resolve_env_vars("$NONEXISTENT_DOTO_VAR") == ""

    def test_literal_passthrough(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        assert resolve_env_vars("literal") == "literal"

    def test_resolve_user_fallback(self) -> None:
        from doxtr_doto.cli.config import resolve_user

        with patch.dict(os.environ, {"USER": "fallback_user"}):
            assert resolve_user("") == "fallback_user"

    def test_resolve_user_explicit(self) -> None:
        from doxtr_doto.cli.config import resolve_user

        with patch.dict(os.environ, {"MY_USER": "alice"}):
            assert resolve_user("$MY_USER") == "alice"


# ── CLI add with RACI ──────────────────────────────────────────────────────


class TestAddBuildTaskDataRaci:
    """Tests for _build_task_data RACI defaults and explicit override."""

    def test_auto_raci_from_user(self) -> None:
        """When no --raci is given, auto-set R and A from config.user."""
        from doxtr_doto.cli.commands.add import _build_task_data
        from doxtr_doto.cli.config import DotoConfig

        config = DotoConfig(user="alice")
        data = _build_task_data(config, "title", None, None, None, None, None, None, None, None)
        assert data["raci"] == {
            "responsible": ["alice"],
            "accountable": ["alice"],
        }

    def test_explicit_raci_overrides_auto(self) -> None:
        """An explicit --raci string replaces auto-RACI."""
        from doxtr_doto.cli.commands.add import _build_task_data
        from doxtr_doto.cli.config import DotoConfig

        config = DotoConfig(user="alice")
        data = _build_task_data(
            config,
            "title",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            raci="responsible bob",
        )
        assert data["raci"] == {"responsible": ["bob"]}

    def test_no_user_no_raci(self) -> None:
        """When no user is configured and no --raci given, raci is None."""
        from doxtr_doto.cli.commands.add import _build_task_data
        from doxtr_doto.cli.config import DotoConfig

        with patch.dict(os.environ, {}, clear=True):
            config = DotoConfig(user="")
            data = _build_task_data(config, "title", None, None, None, None, None, None, None, None)
        assert data["raci"] is None


# ── CLI update RACI merge ──────────────────────────────────────────────────


class TestUpdateBuildUpdatesRaci:
    """Tests for _build_updates RACI merge behavior."""

    def test_raci_merges_with_existing(self) -> None:
        from doxtr_doto.cli.commands.update import _build_updates

        task: dict[str, Any] = {
            "raci": {"responsible": ["alice"]},
        }
        updates = _build_updates(
            task=task,
            title=None,
            assignee=None,
            priority=None,
            status=None,
            due=None,
            clear_due=False,
            add_tags=None,
            remove_tags=None,
            depends_on=None,
            add_depends=None,
            remove_depends=None,
            body=None,
            edit=False,
            raci="consulted carol",
        )
        assert updates["raci"] == {
            "responsible": ["alice"],
            "consulted": ["carol"],
        }

    def test_raci_no_flag_no_update(self) -> None:
        from doxtr_doto.cli.commands.update import _build_updates

        task: dict[str, Any] = {"raci": {"responsible": ["alice"]}}
        updates = _build_updates(
            task=task,
            title=None,
            assignee=None,
            priority=None,
            status=None,
            due=None,
            clear_due=False,
            add_tags=None,
            remove_tags=None,
            depends_on=None,
            add_depends=None,
            remove_depends=None,
            body=None,
            edit=False,
            raci=None,
        )
        assert "raci" not in updates


# ── Fields registry ─────────────────────────────────────────────────────────


class TestRaciField:
    """Test that the raci field is present in the field registry."""

    def test_raci_in_task_fields(self) -> None:
        from doxtr_doto.fields import TASK_FIELDS

        names = [f.name for f in TASK_FIELDS]
        assert "raci" in names

    def test_raci_by_name(self) -> None:
        from doxtr_doto.fields import BY_NAME

        field = BY_NAME["raci"]
        assert field.rst_name == "raci"
        assert field.json_name == "raci"
        assert field.display_label == "RACI"
        assert field.mergeable is True
        assert field.displayable is True
        assert field.serializable is True
        assert field.default is None


# ── JSON round-trip ─────────────────────────────────────────────────────────


class TestJsonRoundTrip:
    """Test that RACI survives JSON store round-trip."""

    def test_add_and_get_raci(self, doto_srcdir: Path) -> None:
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = doto_srcdir / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)

        task_data: dict[str, Any] = {
            "title": "Test",
            "raci": {"responsible": ["alice"], "accountable": ["bob"]},
        }
        store.add_task("RACI-RT-001", task_data)
        store.save()

        # Reload
        store2 = JsonTaskStore(json_path)
        task = store2.get_task("RACI-RT-001")
        assert task is not None
        assert task["raci"] == {"responsible": ["alice"], "accountable": ["bob"]}

    def test_update_raci(self, doto_srcdir: Path) -> None:
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = doto_srcdir / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)

        store.add_task("RACI-RT-002", {"title": "Test"})
        store.update_task(
            "RACI-RT-002",
            {"raci": {"consulted": ["carol"]}},
        )
        store.save()

        store2 = JsonTaskStore(json_path)
        task = store2.get_task("RACI-RT-002")
        assert task is not None
        assert task["raci"] == {"consulted": ["carol"]}


# ── TUI EditTaskScreen build_fields / collect (unit, no render) ─────────


class TestEditTaskScreenRaci:
    """Unit-test the EditTaskScreen RACI field helpers."""

    def test_build_fields_includes_raci(self) -> None:
        from doxtr_doto.cli.tui.app import EditTaskScreen

        task: dict[str, Any] = {
            "title": "Test",
            "raci": {"responsible": ["alice"], "consulted": ["carol", "dave"]},
        }
        fields = EditTaskScreen.build_fields(task)
        assert fields["raci_responsible"] == "alice"
        assert fields["raci_consulted"] == "carol, dave"
        assert fields["raci_accountable"] == ""
        assert fields["raci_informed"] == ""

    def test_build_fields_no_raci(self) -> None:
        from doxtr_doto.cli.tui.app import EditTaskScreen

        fields = EditTaskScreen.build_fields({"title": "Test"})
        assert fields["raci_responsible"] == ""
        assert fields["raci_accountable"] == ""


# ── Sphinx config ───────────────────────────────────────────────────────────


class TestSphinxDefaultUser:
    """Test that doto_default_user is registered."""

    def test_default_user_in_defaults(self) -> None:
        from doxtr_doto.config import DEFAULTS

        assert "doto_default_user" in DEFAULTS
        assert DEFAULTS["doto_default_user"] == ""


# ── split_names / dedup_names helpers ───────────────────────────────────────


class TestSplitNames:
    """Tests for the shared split_names helper."""

    def test_empty(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("") == []

    def test_simple(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("alice, bob") == ["alice", "bob"]

    def test_strips_whitespace(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("  alice , bob  ") == ["alice", "bob"]

    def test_drops_empties(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("alice,,bob,") == ["alice", "bob"]

    def test_case_insensitive_dedup(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("Alice, alice, ALICE") == ["Alice"]

    def test_order_preserving(self) -> None:
        from doxtr_doto.raci import split_names

        assert split_names("bob, alice, carol") == ["bob", "alice", "carol"]


class TestDedupNames:
    """Tests for the shared dedup_names helper."""

    def test_empty(self) -> None:
        from doxtr_doto.raci import dedup_names

        assert dedup_names([]) == []

    def test_case_insensitive_first_wins(self) -> None:
        from doxtr_doto.raci import dedup_names

        assert dedup_names(["Alice", "alice", "ALICE"]) == ["Alice"]

    def test_preserves_order(self) -> None:
        from doxtr_doto.raci import dedup_names

        assert dedup_names(["bob", "alice", "carol"]) == ["bob", "alice", "carol"]


# ── TUI collect_raci via build_fields + logic ───────────────────────────────


class TestCollectRaciLogic:
    """Test TUI collect_raci logic (pure, without rendering).

    We exercise the split_names-based dedup that collect_raci delegates to,
    and verify that build_fields correctly populates and round-trips RACI data
    through the field names that collect_raci will read.
    """

    def test_build_fields_round_trip(self) -> None:
        """build_fields populates the four role keys that collect_raci reads."""
        from doxtr_doto.cli.tui.app import EditTaskScreen

        task: dict[str, Any] = {
            "title": "Test",
            "raci": {
                "responsible": ["alice", "bob"],
                "accountable": ["carol"],
            },
        }
        fields = EditTaskScreen.build_fields(task)
        assert fields["raci_responsible"] == "alice, bob"
        assert fields["raci_accountable"] == "carol"
        assert fields["raci_consulted"] == ""
        assert fields["raci_informed"] == ""

    def test_split_names_dedup_for_collect(self) -> None:
        """split_names performs the same dedup that collect_raci delegates to."""
        from doxtr_doto.raci import split_names

        # Duplicate names (case-insensitive) are deduped
        assert split_names("alice, Alice, bob") == ["alice", "bob"]

    def test_all_empty_is_none(self) -> None:
        """When all four role fields are empty, collect_raci returns None."""
        from doxtr_doto.raci import split_names

        for raw in ["", "   ", ",,,"]:
            assert split_names(raw) == []


# ── RACI → known_names persistence ──────────────────────────────────────────


class TestRaciKnownNamesPersistence:
    """Test that RACI names are persisted to known_names."""

    def test_add_with_raci_persists_names(self, tmp_path: Path, monkeypatch: Any) -> None:
        """doto add with --raci persists RACI names to known_names."""
        from click.testing import CliRunner

        from doxtr_doto.cli import known_names
        from doxtr_doto.cli.main import cli

        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()
        (doto_dir / "tasks.json").write_text('{"version": 2, "tasks": {}}')

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "add",
                "Test RACI persist",
                "--raci",
                "responsible alice, accountable bob",
            ],
        )
        assert result.exit_code == 0, result.output

        kn_path = doto_dir / "known_names.json"
        assignees = known_names.get_assignees(path=kn_path)
        # Both alice and bob should be in known assignees
        lower_names = [n.lower() for n in assignees]
        assert "alice" in lower_names
        assert "bob" in lower_names


# ── register_raci_html_renderer / compact renderer seam ─────────────────────


class TestRendererSeams:
    """Test register/reset for both HTML and compact renderer seams."""

    def test_register_html_renderer(self) -> None:
        from doxtr_doto.raci import (
            register_raci_html_renderer,
            render_raci_html,
            reset_raci_html_renderer,
        )

        try:
            stub_called: list[Any] = []

            def stub_renderer(raci: dict[str, list[str]] | None) -> str:
                stub_called.append(raci)
                return "<stub>"

            register_raci_html_renderer(stub_renderer)
            raci = {"responsible": ["alice"]}
            result = render_raci_html(raci)
            assert result == "<stub>"
            assert stub_called == [raci]
        finally:
            reset_raci_html_renderer()

        # After reset, default renderer is active again
        html = render_raci_html({"responsible": ["alice"]})
        assert "doto-raci" in html

    def test_register_compact_renderer(self) -> None:
        from doxtr_doto.raci import (
            register_raci_compact_renderer,
            render_raci_compact,
            reset_raci_compact_renderer,
        )

        try:
            stub_called: list[Any] = []

            def stub_compact(raci: dict[str, list[str]] | None) -> str:
                stub_called.append(raci)
                return "STUB-COMPACT"

            register_raci_compact_renderer(stub_compact)
            raci = {"responsible": ["alice"]}
            result = render_raci_compact(raci)
            assert result == "STUB-COMPACT"
            assert stub_called == [raci]
        finally:
            reset_raci_compact_renderer()

        # After reset, default compact renderer is active again
        assert render_raci_compact({"responsible": ["alice"]}) == "R: alice"

    def test_register_differing_renderer(self) -> None:
        from doxtr_doto.raci import (
            register_raci_differing_renderer,
            render_raci_differing_lines,
            reset_raci_differing_renderer,
        )

        try:
            stub_called: list[Any] = []

            def stub_differing(raci: dict[str, list[str]] | None, user: str) -> list[str]:
                stub_called.append((raci, user))
                return ["STUB-DIFFERING"]

            register_raci_differing_renderer(stub_differing)
            raci = {"responsible": ["bob"]}
            result = render_raci_differing_lines(raci, "alice")
            assert result == ["STUB-DIFFERING"]
            assert stub_called == [(raci, "alice")]
        finally:
            reset_raci_differing_renderer()

        # After reset, the default differing renderer is active again.
        from rich.text import Text

        lines = render_raci_differing_lines({"responsible": ["bob"]}, "alice")
        plain = Text.from_markup("\n".join(lines)).plain
        assert "Responsible: bob" in plain


# ── filter_raci_differing / render_raci_differing_lines (TUI popup) ──────────


class TestFilterRaciDiffering:
    """Filter RACI entries against the configured default user."""

    def test_empty_or_none_raci(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        assert filter_raci_differing(None, "alice") == {}
        assert filter_raci_differing({}, "alice") == {}

    def test_role_fully_suppressed_when_only_default_user(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        # The one name equals the default user, so the whole role drops out.
        assert filter_raci_differing({"responsible": ["alice"]}, "alice") == {}

    def test_role_shown_when_name_differs(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        assert filter_raci_differing({"responsible": ["bob"]}, "alice") == {"responsible": ["bob"]}

    def test_case_insensitive_default_user_match(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        # "Alice" (title case in RACI) matches default user "alice".
        assert filter_raci_differing({"responsible": ["Alice"]}, "alice") == {}
        # And the reverse (default user "ALICE" vs RACI "alice").
        assert filter_raci_differing({"responsible": ["alice"]}, "ALICE") == {}

    def test_multiple_names_keeps_non_default(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        assert filter_raci_differing({"responsible": ["alice", "bob"]}, "alice") == {
            "responsible": ["bob"]
        }

    def test_empty_default_user_keeps_everything(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        raci = {"responsible": ["alice"], "accountable": ["bob"]}
        assert filter_raci_differing(raci, "") == raci

    def test_empty_default_user_normalises_role_order(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        # Scrambled input order with no default user: nothing is suppressed,
        # but the kept roles follow R-A-C-I, not insertion order.
        result = filter_raci_differing({"informed": ["x"], "responsible": ["y"]}, "")
        assert list(result.keys()) == ["responsible", "informed"]

    def test_role_order_normalised_to_raci(self) -> None:
        from doxtr_doto.raci import filter_raci_differing

        # Input order informed-before-responsible; output follows R-A-C-I.
        result = filter_raci_differing({"informed": ["carol"], "responsible": ["bob"]}, "alice")
        assert list(result.keys()) == ["responsible", "informed"]


class TestRenderRaciDifferingLines:
    """Render RACI detail lines, suppressing the default-user-only roles."""

    def test_empty_when_nothing_differs(self) -> None:
        from doxtr_doto.raci import render_raci_differing_lines

        assert render_raci_differing_lines(None, "alice") == []
        assert render_raci_differing_lines({}, "alice") == []
        # Every role is only the default user -> nothing to show.
        assert render_raci_differing_lines({"responsible": ["alice"]}, "alice") == []

    def test_renders_differing_roles_with_labels(self) -> None:
        from rich.text import Text

        from doxtr_doto.raci import render_raci_differing_lines

        raci = {"responsible": ["alice", "bob"], "consulted": ["carol"]}
        lines = render_raci_differing_lines(raci, "alice")
        plain = Text.from_markup("\n".join(lines)).plain
        # alice (default) suppressed from responsible; bob kept; consulted kept.
        assert "Responsible: bob" in plain
        assert "Consulted: carol" in plain
        assert "alice" not in plain

    def test_escapes_markup_in_names(self) -> None:
        from rich.text import Text

        from doxtr_doto.raci import render_raci_differing_lines

        lines = render_raci_differing_lines({"responsible": ["[bot] bob"]}, "alice")
        plain = Text.from_markup("\n".join(lines)).plain
        assert "[bot] bob" in plain


# ── Malformed :raci: directive ──────────────────────────────────────────────


class TestMalformedRaciDirective:
    """Test that invalid :raci: in a directive raises a Sphinx error."""

    def test_invalid_role_name_warns(self, doto_srcdir: Path, make_app: Any) -> None:
        """An unrecognised role in :raci: produces a Sphinx warning."""
        import io

        from sphinx.application import Sphinx

        bad_rst = doto_srcdir / "bad_raci.rst"
        bad_rst.write_text(
            "Bad RACI\n========\n\n"
            ".. doto:: Bad raci task\n"
            "   :id: BAD-RACI-001\n"
            "   :raci: owner alice\n\n"
            "   A task with bad raci.\n"
        )
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   bad_raci\n")

        warning_stream = io.StringIO()
        app = Sphinx(
            srcdir=str(doto_srcdir),
            confdir=str(doto_srcdir),
            outdir=str(doto_srcdir / "_build" / "html-bad"),
            doctreedir=str(doto_srcdir / "_build" / ".doctrees-bad"),
            buildername="html",
            warning=warning_stream,
            freshenv=True,
        )
        app.build()

        warnings = warning_stream.getvalue()
        assert "Unknown RACI role" in warnings or "Invalid :raci:" in warnings


# ── Integration: RACI in built HTML output ──────────────────────────────────


class TestRaciHtmlIntegration:
    """Integration test: RACI appears in the built HTML output."""

    def test_raci_in_single_task_html(self, doto_srcdir: Path, make_app: Any) -> None:
        raci_rst = doto_srcdir / "raci_html.rst"
        raci_rst.write_text(
            "RACI HTML\n=========\n\n"
            ".. doto:: HTML raci task\n"
            "   :id: RACI-HTML-001\n"
            "   :raci: responsible alice, accountable bob\n\n"
            "   Body text.\n"
        )
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   raci_html\n")

        app = make_app(srcdir=doto_srcdir, buildername="html")
        app.build()

        html = (Path(app.outdir) / "raci_html.html").read_text()
        assert "doto-raci" in html
        assert "Responsible" in html
        assert "alice" in html


# ── Integration: RACI in built LaTeX output ─────────────────────────────────


class TestRaciLatexIntegration:
    """Integration test: RACI appears in the built LaTeX output."""

    def test_raci_in_single_task_latex(self, doto_srcdir: Path, make_app: Any) -> None:
        raci_rst = doto_srcdir / "raci_latex.rst"
        raci_rst.write_text(
            "RACI LaTeX\n==========\n\n"
            ".. doto:: LaTeX raci task\n"
            "   :id: RACI-LATEX-001\n"
            "   :raci: responsible alice, accountable bob\n\n"
            "   Body text.\n"
        )
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   raci_latex\n")

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.build()

        # Find a .tex file in the output
        tex_files = list(Path(app.outdir).glob("*.tex"))
        assert tex_files, "No .tex files produced"
        tex = tex_files[0].read_text()
        assert "dotometaraci" in tex
        assert "alice" in tex


# ── Env var edge cases ──────────────────────────────────────────────────────


class TestResolveEnvVarsEdgeCases:
    """Edge-case tests for resolve_env_vars."""

    def test_mixed_literal_and_var(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"USER": "alice"}):
            assert resolve_env_vars("team-$USER") == "team-alice"

    def test_multiple_refs(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"A": "hello", "B": "world"}):
            assert resolve_env_vars("$A-$B") == "hello-world"

    def test_braced_missing(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {}, clear=True):
            assert resolve_env_vars("${MISSING}") == ""

    def test_mixed_braced_and_unbraced(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"X": "a", "Y": "b"}):
            assert resolve_env_vars("${X}.$Y") == "a.b"

    def test_braced_missing_in_context(self) -> None:
        from doxtr_doto.cli.config import resolve_env_vars

        with patch.dict(os.environ, {"USER": "alice"}, clear=True):
            assert resolve_env_vars("${MISSING}-$USER") == "-alice"


# ── RACI_ROLE_LABELS export ─────────────────────────────────────────────────


class TestRaciRoleLabels:
    """Test that RACI_ROLE_LABELS is correct and consistent."""

    def test_labels_match_roles(self) -> None:
        from doxtr_doto.raci import RACI_ROLE_LABELS, RACI_ROLES

        assert list(RACI_ROLE_LABELS.keys()) == list(RACI_ROLES)
        for role in RACI_ROLES:
            assert RACI_ROLE_LABELS[role] == role.title()

    def test_tui_raci_fields_match_roles(self) -> None:
        """EditTaskScreen.RACI_FIELDS is derived from RACI_ROLE_LABELS."""
        from doxtr_doto.cli.tui.app import EditTaskScreen
        from doxtr_doto.raci import RACI_ROLES

        roles_from_fields = [role for role, _, _ in EditTaskScreen.RACI_FIELDS]
        assert roles_from_fields == list(RACI_ROLES)
