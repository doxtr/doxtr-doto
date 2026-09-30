"""Tests for doxtr_doto.enums module.

These tests verify that all enums are properly defined, their values
are strings for backward compatibility, and they work correctly in
comparisons with raw string literals.
"""

from __future__ import annotations

import pytest

from doxtr_doto.enums import (
    ChartType,
    ConflictResolution,
    DotoIntegration,
    ListFormat,
    SyncAction,
    TaskSource,
)


class TestSyncAction:
    """Tests for SyncAction enum."""

    def test_values_are_strings(self) -> None:
        """Verify all SyncAction values are string instances."""
        assert isinstance(SyncAction.CREATE, str)
        assert isinstance(SyncAction.UPDATE, str)
        assert isinstance(SyncAction.REMOVE, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals (backward compat)."""
        assert SyncAction.CREATE == "create"
        assert SyncAction.UPDATE == "update"
        assert SyncAction.REMOVE == "remove"

    def test_all_values(self) -> None:
        """Verify all expected values exist."""
        values = {e.value for e in SyncAction}
        assert values == {"create", "update", "remove"}

    def test_can_use_in_string_operations(self) -> None:
        """Verify enums can be used in string formatting."""
        # Explicit value access for f-strings
        assert f"Action: {SyncAction.CREATE.value}" == "Action: create"
        # String methods work directly
        assert SyncAction.UPDATE.upper() == "UPDATE"


class TestConflictResolution:
    """Tests for ConflictResolution enum."""

    def test_values_are_strings(self) -> None:
        """Verify all ConflictResolution values are string instances."""
        assert isinstance(ConflictResolution.ERROR, str)
        assert isinstance(ConflictResolution.WARN, str)
        assert isinstance(ConflictResolution.PREFER_RST, str)
        assert isinstance(ConflictResolution.PREFER_JSON, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals."""
        assert ConflictResolution.ERROR == "error"
        assert ConflictResolution.WARN == "warn"
        assert ConflictResolution.PREFER_RST == "prefer-rst"
        assert ConflictResolution.PREFER_JSON == "prefer-json"

    def test_covers_all_config_values(self) -> None:
        """Verify enum covers all valid configuration values."""
        valid_config_values = {"error", "warn", "prefer-rst", "prefer-json"}
        enum_values = {e.value for e in ConflictResolution}
        assert enum_values == valid_config_values

    def test_membership_check(self) -> None:
        """Verify membership checks work with string values."""
        valid_actions = {e.value for e in ConflictResolution}
        assert "error" in valid_actions
        assert "warn" in valid_actions
        assert "invalid" not in valid_actions


class TestDotoIntegration:
    """Tests for DotoIntegration enum."""

    def test_values_are_strings(self) -> None:
        """Verify all DotoIntegration values are string instances."""
        assert isinstance(DotoIntegration.AUTO, str)
        assert isinstance(DotoIntegration.ENABLED, str)
        assert isinstance(DotoIntegration.DISABLED, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals."""
        assert DotoIntegration.AUTO == "auto"
        assert DotoIntegration.ENABLED == "enabled"
        assert DotoIntegration.DISABLED == "disabled"

    def test_all_values(self) -> None:
        """Verify all expected values exist."""
        values = {e.value for e in DotoIntegration}
        assert values == {"auto", "enabled", "disabled"}


class TestTaskSource:
    """Tests for TaskSource enum."""

    def test_values_are_strings(self) -> None:
        """Verify all TaskSource values are string instances."""
        assert isinstance(TaskSource.RST, str)
        assert isinstance(TaskSource.JSON, str)
        assert isinstance(TaskSource.MERGED, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals."""
        assert TaskSource.RST == "rst"
        assert TaskSource.JSON == "json"
        assert TaskSource.MERGED == "merged"

    def test_roundtrip_from_json(self) -> None:
        """Verify TaskSource can roundtrip through JSON serialization."""
        import json

        # Serialize
        data = {"source": TaskSource.RST}
        json_str = json.dumps(data)

        # Deserialize and compare
        loaded = json.loads(json_str)
        assert loaded["source"] == TaskSource.RST.value
        assert loaded["source"] == "rst"

    def test_all_values(self) -> None:
        """Verify all expected values exist."""
        values = {e.value for e in TaskSource}
        assert values == {"rst", "json", "merged"}


class TestChartType:
    """Tests for ChartType enum."""

    def test_values_are_strings(self) -> None:
        """Verify all ChartType values are string instances."""
        assert isinstance(ChartType.BAR, str)
        assert isinstance(ChartType.PIE, str)
        assert isinstance(ChartType.STACKED_BAR, str)
        assert isinstance(ChartType.PROGRESS, str)
        assert isinstance(ChartType.BURNDOWN, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals."""
        assert ChartType.BAR == "bar"
        assert ChartType.PIE == "pie"
        assert ChartType.STACKED_BAR == "stacked-bar"
        assert ChartType.PROGRESS == "progress"
        assert ChartType.BURNDOWN == "burndown"

    def test_all_values(self) -> None:
        """Verify all expected values exist."""
        values = {e.value for e in ChartType}
        assert values == {"bar", "pie", "stacked-bar", "progress", "burndown"}

    def test_matches_charts_valid_chart_types(self) -> None:
        """Verify enum values match the authoritative VALID_CHART_TYPES set."""
        from doxtr_doto.charts import VALID_CHART_TYPES

        enum_values = {e.value for e in ChartType}
        assert enum_values == set(VALID_CHART_TYPES)


class TestListFormat:
    """Tests for ListFormat enum."""

    def test_values_are_strings(self) -> None:
        """Verify all ListFormat values are string instances."""
        assert isinstance(ListFormat.TABLE, str)
        assert isinstance(ListFormat.LIST, str)
        assert isinstance(ListFormat.CARDS, str)

    def test_string_comparison(self) -> None:
        """Verify enums can be compared with string literals."""
        assert ListFormat.TABLE == "table"
        assert ListFormat.LIST == "list"
        assert ListFormat.CARDS == "cards"

    def test_matches_directive_valid_formats(self) -> None:
        """Verify enum values match VALID_FORMATS in doto_list directive."""
        from doxtr_doto.directives.doto_list import VALID_FORMATS

        enum_values = {e.value for e in ListFormat}
        assert enum_values == VALID_FORMATS

    def test_all_values(self) -> None:
        """Verify all expected values exist."""
        values = {e.value for e in ListFormat}
        assert values == {"table", "list", "cards"}


class TestTaskSourceIntegrationWithDotoTask:
    """Integration tests for TaskSource with DotoTask."""

    def test_from_dict_sets_source_to_json(self) -> None:
        """Verify DotoTask.from_dict() sets source to TaskSource.JSON."""
        from doxtr_doto.collectors import DotoTask

        data = {
            "title": "Test Task",
            "priority": "high",
            "status": "open",
            "tags": [],
            "depends_on": [],
            "body": "",
            "created": "2024-01-15T10:00:00",
            "updated": "2024-01-15T10:00:00",
        }
        task = DotoTask.from_dict("TASK-001", data)
        
        assert task.source == TaskSource.JSON
        assert task.source == "json"  # Backward compat with string comparison

    def test_default_doto_task_source_is_rst(self) -> None:
        """Verify default DotoTask source is TaskSource.RST."""
        from doxtr_doto.collectors import DotoTask

        task = DotoTask(id="TASK-002", title="Direct Task")
        
        assert task.source == TaskSource.RST
        assert task.source == "rst"  # Backward compat with string comparison

    def test_source_can_be_explicitly_set(self) -> None:
        """Verify source can be explicitly set to any TaskSource value."""
        from doxtr_doto.collectors import DotoTask

        task = DotoTask(id="TASK-003", title="Merged Task", source=TaskSource.MERGED)
        
        assert task.source == TaskSource.MERGED
        assert task.source == "merged"


class TestEnumInheritance:
    """Tests for enum inheritance behavior."""

    def test_all_enums_inherit_from_str(self) -> None:
        """Verify all enums inherit from str for backward compatibility."""
        enums = [
            SyncAction,
            ConflictResolution,
            DotoIntegration,
            TaskSource,
            ChartType,
            ListFormat,
        ]
        for enum_class in enums:
            for member in enum_class:
                assert isinstance(member, str), f"{enum_class.__name__}.{member.name} is not a str"

    def test_enums_work_in_set_membership(self) -> None:
        """Verify enums work in set membership checks with strings."""
        valid_set = {"create", "update", "remove"}
        assert SyncAction.CREATE in valid_set
        assert SyncAction.UPDATE in valid_set
        assert SyncAction.REMOVE in valid_set

    def test_enums_work_in_dict_keys(self) -> None:
        """Verify enums work as dict keys interchangeably with strings."""
        d = {"create": 1, "update": 2}
        assert d[SyncAction.CREATE] == 1
        assert d[SyncAction.UPDATE] == 2

        # And the reverse
        d2 = {SyncAction.CREATE: 1, SyncAction.UPDATE: 2}
        assert d2["create"] == 1
        assert d2["update"] == 2
