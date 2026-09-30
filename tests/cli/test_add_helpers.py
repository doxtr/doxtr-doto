"""Tests for add command helper functions."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from doxtr_doto.cli.commands.add import (
    _build_task_data,
    _prompt_missing_fields,
    _resolve_title_from_editor,
)

# The package ``doxtr_doto.cli.commands`` re-exports the ``add`` Click *command*
# (``from ...add import add``), which shadows the ``add`` *submodule* name in the
# package namespace. A plain ``import doxtr_doto.cli.commands.add as add_module``
# would therefore bind the Command object, not the module. ``import_module``
# returns the real module from ``sys.modules`` regardless of the shadowing.
#
# Patch targets below use ``patch.object(add_module, ...)`` instead of the dotted
# string "doxtr_doto.cli.commands.add.<attr>". On Python 3.10, ``unittest.mock``
# resolves dotted targets with a plain ``getattr`` walk, so "...commands.add"
# resolves to the Command object and raises
# ``AttributeError: <Command add> does not have the attribute 'open_editor'``.
# Python 3.11+ resolves via ``pkgutil.resolve_name`` and imports the submodule.
# Patching the resolved module object is unambiguous on all supported versions.
add_module = importlib.import_module("doxtr_doto.cli.commands.add")


@dataclass
class MockConfig:
    """Mock DotoConfig for testing."""

    priorities: list[str] = None
    statuses: list[str] = None
    default_priority: str = "medium"
    default_status: str = "open"
    default_assignee: str | None = None

    def __post_init__(self):
        if self.priorities is None:
            self.priorities = ["low", "medium", "high", "critical"]
        if self.statuses is None:
            self.statuses = ["open", "in-progress", "done", "blocked"]


class TestBuildTaskData:
    """Tests for _build_task_data helper."""

    def test_basic_task_data(self):
        """Build task data with minimal required fields."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Test task",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags=None,
            depends_on=None,
            body=None,
            rst_file=None,
        )

        assert result["title"] == "Test task"
        assert result["priority"] == "medium"  # default
        assert result["status"] == "open"  # default
        assert result["assignee"] is None
        assert result["due"] is None
        assert result["tags"] == []
        assert result["depends_on"] == []
        assert result["body"] is None
        assert "_sync" not in result

    def test_all_fields_provided(self):
        """Build task data with all fields provided."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Complete task",
            assignee="alice",
            priority="high",
            status="in-progress",
            due="2025-12-31",
            tags="bug,urgent",
            depends_on="DOTO-001,DOTO-002",
            body="Task description here",
            rst_file=None,
        )

        assert result["title"] == "Complete task"
        assert result["assignee"] == "alice"
        assert result["priority"] == "high"
        assert result["status"] == "in-progress"
        assert result["due"] == "2025-12-31"
        assert result["tags"] == ["bug", "urgent"]
        assert result["depends_on"] == ["DOTO-001", "DOTO-002"]
        assert result["body"] == "Task description here"

    def test_tags_parsing(self):
        """Tags are parsed from comma-separated string."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Test",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags="  tag1 , tag2 ,  tag3  ",
            depends_on=None,
            body=None,
            rst_file=None,
        )

        assert result["tags"] == ["tag1", "tag2", "tag3"]

    def test_tags_empty_string(self):
        """Empty tags string produces empty list."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Test",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags="",
            depends_on=None,
            body=None,
            rst_file=None,
        )

        assert result["tags"] == []

    def test_depends_on_parsing(self):
        """Dependencies are parsed from comma-separated string."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Test",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags=None,
            depends_on=" DOTO-001 , DOTO-002 ",
            body=None,
            rst_file=None,
        )

        assert result["depends_on"] == ["DOTO-001", "DOTO-002"]

    def test_rst_file_adds_sync_metadata(self):
        """RST file parameter adds _sync metadata."""
        config = MockConfig()
        result = _build_task_data(
            config=config,
            title="Test",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags=None,
            depends_on=None,
            body=None,
            rst_file="docs/tasks.rst",
        )

        assert "_sync" in result
        assert result["_sync"]["rst_file"] == "docs/tasks.rst"
        assert result["_sync"]["rst_line"] is None
        assert result["_sync"]["rst_hash"] is None
        assert result["_sync"]["snapshot"] is None

    def test_config_default_assignee_used(self):
        """Config default assignee is used when assignee not provided."""
        config = MockConfig(default_assignee="bob")
        result = _build_task_data(
            config=config,
            title="Test",
            assignee=None,
            priority=None,
            status=None,
            due=None,
            tags=None,
            depends_on=None,
            body=None,
            rst_file=None,
        )

        assert result["assignee"] == "bob"

    def test_explicit_assignee_overrides_default(self):
        """Explicit assignee overrides config default."""
        config = MockConfig(default_assignee="bob")
        result = _build_task_data(
            config=config,
            title="Test",
            assignee="alice",
            priority=None,
            status=None,
            due=None,
            tags=None,
            depends_on=None,
            body=None,
            rst_file=None,
        )

        assert result["assignee"] == "alice"


class TestResolveTitleFromEditor:
    """Tests for _resolve_title_from_editor helper."""

    @patch.object(add_module, "open_editor")
    def test_extracts_title_from_first_line(self, mock_editor):
        """Title is extracted from first line of editor content."""
        mock_editor.return_value = "My task title\n\nTask body here"
        
        title, body = _resolve_title_from_editor(None)
        
        assert title == "My task title"
        assert body == "Task body here"

    @patch.object(add_module, "open_editor")
    def test_strips_hash_from_title(self, mock_editor):
        """Leading hash is stripped from title."""
        mock_editor.return_value = "# My task title\n\nTask body"
        
        title, body = _resolve_title_from_editor(None)
        
        assert title == "My task title"

    @patch.object(add_module, "open_editor")
    def test_preserves_existing_body_if_no_new_body(self, mock_editor):
        """Existing body is preserved if editor content has no body."""
        mock_editor.return_value = "My task title\n"
        
        title, body = _resolve_title_from_editor("Existing body")
        
        assert title == "My task title"
        assert body == "Existing body"

    @patch.object(add_module, "open_editor")
    def test_new_body_replaces_existing(self, mock_editor):
        """New body from editor replaces existing body."""
        mock_editor.return_value = "My task title\n\nNew body content"
        
        title, body = _resolve_title_from_editor("Old body")
        
        assert title == "My task title"
        assert body == "New body content"

    @patch.object(add_module, "open_editor")
    def test_multiline_body(self, mock_editor):
        """Multi-line body is preserved."""
        mock_editor.return_value = "Task title\n\nLine 1\nLine 2\nLine 3"
        
        title, body = _resolve_title_from_editor(None)
        
        assert title == "Task title"
        assert body == "Line 1\nLine 2\nLine 3"


class TestPromptMissingFields:
    """Tests for _prompt_missing_fields helper."""

    @patch.object(add_module.click, "prompt")
    @patch.object(add_module.click, "confirm")
    def test_prompts_for_missing_title(self, mock_confirm, mock_prompt):
        """Prompts for title when not provided."""
        mock_prompt.side_effect = ["New title", "", "medium", "open", "", ""]
        mock_confirm.return_value = False
        config = MockConfig()
        
        result = _prompt_missing_fields(
            config, None, None, None, None, None, None, None
        )
        
        assert result[0] == "New title"  # title
        mock_prompt.assert_any_call("Title")

    @patch.object(add_module.click, "prompt")
    @patch.object(add_module.click, "confirm")
    def test_skips_prompt_if_title_provided(self, mock_confirm, mock_prompt):
        """Does not prompt for title when already provided."""
        mock_prompt.side_effect = ["", "medium", "open", "", ""]
        mock_confirm.return_value = False
        config = MockConfig()
        
        result = _prompt_missing_fields(
            config, "Existing title", None, None, None, None, None, None
        )
        
        assert result[0] == "Existing title"

    @patch.object(add_module.click, "prompt")
    @patch.object(add_module.click, "confirm")
    def test_returns_all_fields(self, mock_confirm, mock_prompt):
        """Returns tuple of all fields."""
        mock_prompt.side_effect = [
            "Title",
            "alice",
            "high",
            "in-progress",
            "2025-12-31",
            "bug,feature",
        ]
        mock_confirm.return_value = False
        config = MockConfig()
        
        result = _prompt_missing_fields(
            config, None, None, None, None, None, None, None
        )
        
        assert len(result) == 7  # title, assignee, priority, status, due, tags, body
        title, assignee, priority, status, due, tags, body = result
        assert title == "Title"
        assert assignee == "alice"
        assert priority == "high"
        assert status == "in-progress"
        assert due == "2025-12-31"
        assert tags == "bug,feature"
        assert body is None  # confirm returned False

    @patch.object(add_module.click, "prompt")
    @patch.object(add_module.click, "confirm")
    @patch.object(add_module, "open_editor")
    def test_opens_editor_for_body_if_confirmed(self, mock_editor, mock_confirm, mock_prompt):
        """Opens editor for body when user confirms."""
        mock_prompt.side_effect = ["Title", "", "medium", "open", "", ""]
        mock_confirm.return_value = True
        mock_editor.return_value = "Task description"
        config = MockConfig()
        
        result = _prompt_missing_fields(
            config, None, None, None, None, None, None, None
        )
        
        assert result[6] == "Task description"  # body
        mock_editor.assert_called_once()

    @patch.object(add_module.click, "prompt")
    @patch.object(add_module.click, "confirm")
    def test_preserves_provided_values(self, mock_confirm, mock_prompt):
        """Does not prompt for already-provided values."""
        mock_confirm.return_value = False
        config = MockConfig()
        
        # Provide all values except body
        result = _prompt_missing_fields(
            config, "Title", "alice", "high", "open", "2025-12-31", "bug", None
        )
        
        # Should not prompt at all (except for body confirmation)
        assert mock_prompt.call_count == 0
        assert result == ("Title", "alice", "high", "open", "2025-12-31", "bug", None)


class TestListRenderersDispatchTable:
    """Tests for the _LIST_RENDERERS dispatch table in nodes.py."""

    def test_dispatch_table_exists(self):
        """Dispatch table is defined and accessible."""
        from doxtr_doto.nodes import _LIST_RENDERERS
        
        assert _LIST_RENDERERS is not None
        assert isinstance(_LIST_RENDERERS, dict)

    def test_dispatch_table_contains_all_formats(self):
        """Dispatch table contains all expected format types."""
        from doxtr_doto.nodes import _LIST_RENDERERS
        
        assert "table" in _LIST_RENDERERS
        assert "cards" in _LIST_RENDERERS
        assert "list" in _LIST_RENDERERS

    def test_dispatch_table_functions_are_callable(self):
        """All functions in dispatch table are callable."""
        from doxtr_doto.nodes import _LIST_RENDERERS
        
        for format_type, renderer in _LIST_RENDERERS.items():
            assert callable(renderer), f"Renderer for '{format_type}' is not callable"

    def test_dispatch_table_functions_match_expected(self):
        """Dispatch table maps to the correct functions."""
        from doxtr_doto.nodes import (
            _LIST_RENDERERS,
            _render_task_table,
            _render_task_cards,
            _render_task_list,
        )
        
        assert _LIST_RENDERERS["table"] is _render_task_table
        assert _LIST_RENDERERS["cards"] is _render_task_cards
        assert _LIST_RENDERERS["list"] is _render_task_list
