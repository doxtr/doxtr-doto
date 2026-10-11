"""Tests for the known-names memory store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.known_names import (
    _load,
    _merge,
    add_assignee,
    add_tag,
    get_assignees,
    get_tags,
    remember_task_names,
)


class TestMerge:
    """Unit tests for the case-insensitive merge helper."""

    def test_add_new_name(self) -> None:
        assert _merge([], "alice") == ["alice"]

    def test_add_duplicate_same_case(self) -> None:
        assert _merge(["alice"], "alice") == ["alice"]

    def test_add_duplicate_different_case(self) -> None:
        result = _merge(["Alice"], "alice")
        assert result == ["alice"]
        assert len(result) == 1

    def test_sorted_case_insensitively(self) -> None:
        result = _merge([], "bob")
        result = _merge(result, "Alice")
        assert result == ["Alice", "bob"]

    def test_latest_spelling_wins(self) -> None:
        result = _merge(["ALICE", "bob"], "Alice")
        assert result == ["Alice", "bob"]

    def test_empty_name_passthrough(self) -> None:
        # _merge itself doesn't filter empty; add_assignee/add_tag do.
        result = _merge(["alice"], "bob")
        assert result == ["alice", "bob"]


class TestLoadMissingFile:
    """_load returns empty lists when the file is missing."""

    def test_missing_file(self, tmp_path: Path) -> None:
        data = _load(tmp_path / "does_not_exist.json")
        assert data == {"assignees": [], "tags": []}


class TestLoadCorruptFile:
    """_load returns empty lists for corrupt/invalid JSON."""

    def test_corrupt_json(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text("NOT JSON", encoding="utf-8")
        data = _load(p)
        assert data == {"assignees": [], "tags": []}

    def test_json_is_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text("[]", encoding="utf-8")
        data = _load(p)
        assert data == {"assignees": [], "tags": []}

    def test_json_assignees_not_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text('{"assignees": "bad", "tags": []}', encoding="utf-8")
        data = _load(p)
        assert data == {"assignees": [], "tags": []}

    def test_json_tags_not_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text('{"assignees": [], "tags": 42}', encoding="utf-8")
        data = _load(p)
        assert data == {"assignees": [], "tags": []}

    def test_non_string_elements_filtered(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text('{"assignees": ["alice", 123], "tags": [null, "bug"]}', encoding="utf-8")
        data = _load(p)
        assert data == {"assignees": ["alice"], "tags": ["bug"]}


class TestAddAssignee:
    """Integration tests for add_assignee / get_assignees."""

    def test_add_and_get(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("alice", path=p)
        assert get_assignees(path=p) == ["alice"]

    def test_dedup_case_insensitive(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("Alice", path=p)
        add_assignee("alice", path=p)
        names = get_assignees(path=p)
        assert names == ["alice"]
        assert len(names) == 1

    def test_empty_string_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("", path=p)
        assert get_assignees(path=p) == []

    def test_whitespace_only_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("   ", path=p)
        assert get_assignees(path=p) == []

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        p = tmp_path / "subdir" / "known_names.json"
        add_assignee("alice", path=p)
        assert p.exists()
        assert get_assignees(path=p) == ["alice"]

    def test_multiple_names_sorted(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("charlie", path=p)
        add_assignee("alice", path=p)
        add_assignee("bob", path=p)
        assert get_assignees(path=p) == ["alice", "bob", "charlie"]

    def test_get_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        assert get_assignees(path=p) == []


class TestAddTag:
    """Integration tests for add_tag / get_tags."""

    def test_add_and_get(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_tag("frontend", path=p)
        assert get_tags(path=p) == ["frontend"]

    def test_dedup_case_insensitive(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_tag("Bug", path=p)
        add_tag("bug", path=p)
        tags = get_tags(path=p)
        assert tags == ["bug"]
        assert len(tags) == 1

    def test_empty_string_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_tag("", path=p)
        assert get_tags(path=p) == []

    def test_whitespace_only_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_tag("   ", path=p)
        assert get_tags(path=p) == []

    def test_multiple_tags_sorted(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_tag("ux", path=p)
        add_tag("bug", path=p)
        add_tag("feature", path=p)
        assert get_tags(path=p) == ["bug", "feature", "ux"]

    def test_get_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        assert get_tags(path=p) == []


class TestAssigneesAndTagsIndependent:
    """Adding an assignee does not affect tags and vice versa."""

    def test_independent(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        add_assignee("alice", path=p)
        add_tag("frontend", path=p)
        assert get_assignees(path=p) == ["alice"]
        assert get_tags(path=p) == ["frontend"]


class TestCorruptFileRecovery:
    """Adding a name to a corrupt file overwrites with valid data."""

    def test_recover_from_corrupt(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        p.write_text("GARBAGE", encoding="utf-8")
        add_assignee("alice", path=p)
        assert get_assignees(path=p) == ["alice"]
        # Verify the file is now valid JSON
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["assignees"] == ["alice"]
        assert data["tags"] == []


class TestRememberTaskNames:
    """Tests for the consolidated remember_task_names helper."""

    def test_remembers_assignee_and_tags(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        remember_task_names("alice", ["bug", "frontend"], path=p)
        assert get_assignees(path=p) == ["alice"]
        assert get_tags(path=p) == ["bug", "frontend"]

    def test_none_assignee_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        remember_task_names(None, ["bug"], path=p)
        assert get_assignees(path=p) == []
        assert get_tags(path=p) == ["bug"]

    def test_none_tags_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "known_names.json"
        remember_task_names("alice", path=p)
        assert get_assignees(path=p) == ["alice"]
        assert get_tags(path=p) == []

    def test_swallows_exceptions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """remember_task_names never raises, even when persistence fails."""

        def _boom(name: str, *, path: Path | None = None) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("doxtr_doto.cli.known_names.add_assignee", _boom)
        # Must not raise
        remember_task_names("alice", ["bug"])


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli_runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture()
def cli_project(tmp_path: Path) -> Path:
    """Create a minimal doto project for CLI testing."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()

    config_file = tmp_path / ".doto.toml"
    config_file.write_text('[doto]\njson_file = ".doto/tasks.json"\nid_prefix = "TEST"\n')

    json_file = doto_dir / "tasks.json"
    json_file.write_text(json.dumps({"version": 2, "updated": "2026-07-26T10:00:00", "tasks": {}}))

    return tmp_path


class TestAddCommandRemembersNames:
    """doto add persists assignees and tags to the known-names store."""

    def test_add_remembers_assignee_and_tags(
        self,
        cli_runner: CliRunner,
        cli_project: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from doxtr_doto.cli.main import cli

        monkeypatch.chdir(cli_project)
        # Disable the auto-RACI current-user fallback so the test does not
        # depend on the ambient $USER (e.g. "runner" on CI), which would
        # otherwise be remembered as an extra known assignee.
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        monkeypatch.delenv("LOGNAME", raising=False)

        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(cli_project),
                "add",
                "Test task",
                "--assignee",
                "zoe",
                "--tags",
                "frontend,bug",
            ],
        )

        assert result.exit_code == 0, result.output

        kn_path = cli_project / ".doto" / "known_names.json"
        assert get_assignees(path=kn_path) == ["zoe"]
        assert get_tags(path=kn_path) == ["bug", "frontend"]


class TestCompleteAssigneeIncludesKnownNames:
    """complete_assignee returns names only in the memory store."""

    def test_known_name_appears_in_completions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from doxtr_doto.cli.completion import complete_assignee

        kn_path = tmp_path / "known_names.json"
        add_assignee("phantom", path=kn_path)

        # complete_assignee imports known_names.get_assignees at call time and
        # calls it with no task store present. Point it at our test file so
        # the name (which is on no task) still shows up in completions.
        import doxtr_doto.cli.known_names as kn_mod

        original_fn = kn_mod.get_assignees
        monkeypatch.setattr(kn_mod, "get_assignees", lambda **kw: original_fn(path=kn_path))
        items = complete_assignee(None, None, "")  # type: ignore[arg-type]

        names = [item.value for item in items]
        assert "phantom" in names


class TestTagSuggester:
    """Tests for the TUI TagSuggester."""

    def test_completes_last_segment(self) -> None:
        import asyncio

        from doxtr_doto.cli.tui.app import TagSuggester

        suggester = TagSuggester(["frontend", "backend", "bug"])
        result = asyncio.run(suggester.get_suggestion("frontend, bu"))
        assert result == "frontend, bug"
