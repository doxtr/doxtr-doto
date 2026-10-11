"""Tests for the central field registry."""

from __future__ import annotations

import pytest

from doxtr_doto.fields import (
    BY_JSON_NAME,
    BY_NAME,
    BY_RST_NAME,
    COLUMN_LABELS,
    DISPLAY_COLUMNS,
    FIELD_NAME_TO_RST,
    MERGE_FIELDS,
    SERIALIZABLE_FIELDS,
    TASK_FIELDS,
    VALID_COLUMNS,
    FieldDefinition,
)


class TestFieldDefinition:
    """Tests for the FieldDefinition dataclass."""

    def test_field_definition_is_frozen(self) -> None:
        """FieldDefinition instances should be immutable."""
        field = FieldDefinition(
            name="test",
            rst_name="test",
            json_name="test",
            display_label="Test",
        )
        with pytest.raises(AttributeError):
            field.name = "changed"  # type: ignore[misc]

    def test_field_definition_defaults(self) -> None:
        """FieldDefinition should have sensible defaults."""
        field = FieldDefinition(
            name="test",
            rst_name="test",
            json_name="test",
            display_label="Test",
        )
        assert field.mergeable is True
        assert field.displayable is True
        assert field.serializable is True
        assert field.default is None

    def test_field_definition_custom_values(self) -> None:
        """FieldDefinition should accept custom values."""
        field = FieldDefinition(
            name="test",
            rst_name="test-field",
            json_name="test_field",
            display_label="Test Field",
            mergeable=False,
            displayable=False,
            serializable=False,
            default="custom",
        )
        assert field.name == "test"
        assert field.rst_name == "test-field"
        assert field.json_name == "test_field"
        assert field.display_label == "Test Field"
        assert field.mergeable is False
        assert field.displayable is False
        assert field.serializable is False
        assert field.default == "custom"


class TestTaskFields:
    """Tests for the TASK_FIELDS registry."""

    def test_task_fields_is_tuple(self) -> None:
        """TASK_FIELDS should be an immutable tuple."""
        assert isinstance(TASK_FIELDS, tuple)

    def test_task_fields_not_empty(self) -> None:
        """TASK_FIELDS should contain field definitions."""
        assert len(TASK_FIELDS) > 0

    def test_all_entries_are_field_definitions(self) -> None:
        """Every entry in TASK_FIELDS should be a FieldDefinition."""
        for field in TASK_FIELDS:
            assert isinstance(field, FieldDefinition)

    def test_no_duplicate_names(self) -> None:
        """Field names should be unique."""
        names = [f.name for f in TASK_FIELDS]
        assert len(names) == len(set(names)), "Duplicate field names found"

    def test_no_duplicate_rst_names(self) -> None:
        """RST names should be unique."""
        rst_names = [f.rst_name for f in TASK_FIELDS]
        assert len(rst_names) == len(set(rst_names)), "Duplicate RST names found"

    def test_no_duplicate_json_names(self) -> None:
        """JSON names should be unique."""
        json_names = [f.json_name for f in TASK_FIELDS]
        assert len(json_names) == len(set(json_names)), "Duplicate JSON names found"

    def test_expected_fields_exist(self) -> None:
        """Core expected fields should be defined."""
        expected_fields = [
            "title",
            "assignee",
            "priority",
            "status",
            "due",
            "tags",
            "depends_on",
            "body",
            "created",
            "updated",
        ]
        field_names = [f.name for f in TASK_FIELDS]
        for expected in expected_fields:
            assert expected in field_names, f"Expected field '{expected}' not found"


class TestMergeFields:
    """Tests for MERGE_FIELDS derived collection."""

    def test_merge_fields_is_tuple(self) -> None:
        """MERGE_FIELDS should be a tuple."""
        assert isinstance(MERGE_FIELDS, tuple)

    def test_merge_fields_contains_only_mergeable(self) -> None:
        """MERGE_FIELDS should only contain fields marked as mergeable."""
        for field_name in MERGE_FIELDS:
            field = BY_NAME[field_name]
            assert field.mergeable is True, f"Field '{field_name}' is not mergeable"

    def test_all_mergeable_fields_included(self) -> None:
        """All mergeable fields should be in MERGE_FIELDS."""
        for field in TASK_FIELDS:
            if field.mergeable:
                assert field.name in MERGE_FIELDS

    def test_expected_merge_fields(self) -> None:
        """Expected merge fields should be present."""
        expected = ["title", "assignee", "priority", "status", "due", "tags", "depends_on", "body"]
        for field_name in expected:
            assert field_name in MERGE_FIELDS, f"Expected '{field_name}' in MERGE_FIELDS"

    def test_created_updated_not_in_merge_fields(self) -> None:
        """Timestamp fields should not be mergeable."""
        assert "created" not in MERGE_FIELDS
        assert "updated" not in MERGE_FIELDS


class TestDisplayColumns:
    """Tests for display-related collections."""

    def test_display_columns_is_tuple(self) -> None:
        """DISPLAY_COLUMNS should be a tuple."""
        assert isinstance(DISPLAY_COLUMNS, tuple)

    def test_valid_columns_is_frozenset(self) -> None:
        """VALID_COLUMNS should be a frozenset."""
        assert isinstance(VALID_COLUMNS, frozenset)

    def test_valid_columns_includes_id(self) -> None:
        """VALID_COLUMNS should include 'id' even though it's not a field."""
        assert "id" in VALID_COLUMNS

    def test_valid_columns_includes_all_display_columns(self) -> None:
        """VALID_COLUMNS should include all DISPLAY_COLUMNS."""
        for col in DISPLAY_COLUMNS:
            assert col in VALID_COLUMNS

    def test_display_columns_uses_rst_names(self) -> None:
        """DISPLAY_COLUMNS should use RST names (with hyphens)."""
        assert "depends-on" in DISPLAY_COLUMNS
        assert "depends_on" not in DISPLAY_COLUMNS

    def test_body_not_displayable(self) -> None:
        """Body field should not be displayable as a column."""
        assert "body" not in DISPLAY_COLUMNS


class TestLookupMaps:
    """Tests for BY_NAME, BY_RST_NAME, BY_JSON_NAME lookup maps."""

    def test_by_name_lookup(self) -> None:
        """BY_NAME should allow lookup by Python attribute name."""
        assert "title" in BY_NAME
        assert BY_NAME["title"].name == "title"

    def test_by_rst_name_lookup(self) -> None:
        """BY_RST_NAME should allow lookup by RST option name."""
        assert "depends-on" in BY_RST_NAME
        assert BY_RST_NAME["depends-on"].name == "depends_on"

    def test_by_json_name_lookup(self) -> None:
        """BY_JSON_NAME should allow lookup by JSON key name."""
        assert "depends_on" in BY_JSON_NAME
        assert BY_JSON_NAME["depends_on"].name == "depends_on"

    def test_all_fields_in_by_name(self) -> None:
        """All fields should be accessible via BY_NAME."""
        for field in TASK_FIELDS:
            assert field.name in BY_NAME
            assert BY_NAME[field.name] is field

    def test_all_fields_in_by_rst_name(self) -> None:
        """All fields should be accessible via BY_RST_NAME."""
        for field in TASK_FIELDS:
            assert field.rst_name in BY_RST_NAME
            assert BY_RST_NAME[field.rst_name] is field

    def test_all_fields_in_by_json_name(self) -> None:
        """All fields should be accessible via BY_JSON_NAME."""
        for field in TASK_FIELDS:
            assert field.json_name in BY_JSON_NAME
            assert BY_JSON_NAME[field.json_name] is field


class TestFieldNameMapping:
    """Tests for FIELD_NAME_TO_RST mapping."""

    def test_field_name_to_rst_only_differs(self) -> None:
        """FIELD_NAME_TO_RST should only contain fields where name differs from rst_name."""
        for name, rst_name in FIELD_NAME_TO_RST.items():
            assert name != rst_name, f"Field '{name}' has same name and rst_name"

    def test_depends_on_mapping(self) -> None:
        """depends_on should map to depends-on."""
        assert FIELD_NAME_TO_RST.get("depends_on") == "depends-on"

    def test_fields_with_same_names_not_in_mapping(self) -> None:
        """Fields where name equals rst_name should not be in mapping."""
        assert "title" not in FIELD_NAME_TO_RST
        assert "status" not in FIELD_NAME_TO_RST


class TestColumnLabels:
    """Tests for COLUMN_LABELS mapping."""

    def test_column_labels_includes_id(self) -> None:
        """COLUMN_LABELS should include 'id' with label 'ID'."""
        assert COLUMN_LABELS["id"] == "ID"

    def test_column_labels_uses_display_labels(self) -> None:
        """COLUMN_LABELS should use display_label from field definitions."""
        for field in TASK_FIELDS:
            assert COLUMN_LABELS[field.rst_name] == field.display_label

    def test_expected_labels(self) -> None:
        """Expected column labels should be correct."""
        assert COLUMN_LABELS.get("title") == "Title"
        assert COLUMN_LABELS.get("assignee") == "Assignee"
        assert COLUMN_LABELS.get("priority") == "Priority"
        assert COLUMN_LABELS.get("status") == "Status"
        assert COLUMN_LABELS.get("due") == "Due Date"
        assert COLUMN_LABELS.get("depends-on") == "Dependencies"


class TestSerializableFields:
    """Tests for SERIALIZABLE_FIELDS collection."""

    def test_serializable_fields_is_tuple(self) -> None:
        """SERIALIZABLE_FIELDS should be a tuple."""
        assert isinstance(SERIALIZABLE_FIELDS, tuple)

    def test_serializable_fields_contains_only_serializable(self) -> None:
        """SERIALIZABLE_FIELDS should only contain fields marked as serializable."""
        for field_name in SERIALIZABLE_FIELDS:
            field = BY_NAME[field_name]
            assert field.serializable is True

    def test_all_serializable_fields_included(self) -> None:
        """All serializable fields should be in SERIALIZABLE_FIELDS."""
        for field in TASK_FIELDS:
            if field.serializable:
                assert field.name in SERIALIZABLE_FIELDS


class TestFieldRegistryIntegration:
    """Integration tests verifying field registry works with other modules."""

    def test_merge_fields_import_from_merge_module(self) -> None:
        """sync/merge.py should successfully import MERGE_FIELDS."""
        from doxtr_doto.sync.merge import MERGE_FIELDS as imported_merge_fields

        assert imported_merge_fields == MERGE_FIELDS

    def test_adding_field_propagates_to_merge_fields(self) -> None:
        """
        Verify that a new mergeable field in TASK_FIELDS would appear in MERGE_FIELDS.

        This test verifies the design: if we added a new mergeable field to TASK_FIELDS,
        it would automatically be included in MERGE_FIELDS.
        """
        # Count mergeable fields
        mergeable_count = sum(1 for f in TASK_FIELDS if f.mergeable)
        assert len(MERGE_FIELDS) == mergeable_count

    def test_progress_field_exists(self) -> None:
        """Progress field should be defined for future feature."""
        assert "progress" in BY_NAME
        field = BY_NAME["progress"]
        assert field.mergeable is True
        assert field.displayable is True


class TestDotoTaskFieldConsistency:
    """Tests verifying TASK_FIELDS registry aligns with DotoTask dataclass."""

    def test_task_fields_match_dototask_attributes(self) -> None:
        """Verify that field names in TASK_FIELDS exist as DotoTask attributes.

        This test catches drift between the registry and the dataclass.
        Note: 'progress' is intentionally in the registry but not yet in DotoTask
        (will be added in Phase 3.3).
        """
        from dataclasses import fields as dataclass_fields

        from doxtr_doto.collectors import DotoTask

        # Get all attribute names from DotoTask dataclass
        dototask_attrs = {f.name for f in dataclass_fields(DotoTask)}

        # Fields that are intentionally in registry but not yet in DotoTask
        # (will be added in future phases)
        pending_fields = {"progress"}  # Phase 3.3

        # Check each field in the registry
        for field in TASK_FIELDS:
            if field.name in pending_fields:
                # Skip fields that are planned but not yet implemented
                continue
            assert field.name in dototask_attrs, (
                f"Field '{field.name}' is in TASK_FIELDS but not a DotoTask attribute. "
                f"Either add it to DotoTask or mark it as a pending_field."
            )

    def test_core_dototask_fields_in_registry(self) -> None:
        """Verify that core DotoTask fields are present in the registry.

        This is the reverse check: ensure important DotoTask attributes
        are registered in TASK_FIELDS.
        """
        # Core fields that must be in the registry
        # (excludes internal/metadata fields like docname, lineno, content_nodes, etc.)
        core_fields = {
            "title",
            "assignee",
            "priority",
            "status",
            "due",
            "tags",
            "depends_on",
            "body",
            "created",
            "updated",
        }

        registry_field_names = {f.name for f in TASK_FIELDS}

        for field_name in core_fields:
            assert field_name in registry_field_names, (
                f"Core DotoTask field '{field_name}' is missing from TASK_FIELDS registry"
            )


class TestInvalidColumnValidation:
    """Tests for column validation using VALID_COLUMNS."""

    def test_valid_column_accepted(self) -> None:
        """Valid columns from VALID_COLUMNS should be accepted."""
        valid_examples = ["id", "title", "status", "priority", "assignee", "due"]
        for col in valid_examples:
            assert col in VALID_COLUMNS, f"Expected '{col}' to be a valid column"

    def test_invalid_column_not_in_valid_columns(self) -> None:
        """Invalid column names should not be in VALID_COLUMNS."""
        invalid_examples = [
            "invalid",
            "foo",
            "bar",
            "unknown_column",
            "TITLE",  # Case-sensitive
            "Status",  # Case-sensitive
            "_internal",
        ]
        for col in invalid_examples:
            assert col not in VALID_COLUMNS, f"'{col}' should not be a valid column"

    def test_column_validation_pattern(self) -> None:
        """Demonstrate the pattern for validating columns in directives.

        This shows how code should validate columns against VALID_COLUMNS,
        which is the pattern used in doto-list directive.
        """

        def validate_columns(columns: list[str]) -> list[str]:
            """Validate column names and return list of invalid ones."""
            return [col for col in columns if col not in VALID_COLUMNS]

        # Valid columns should pass
        assert validate_columns(["id", "title", "status"]) == []

        # Invalid columns should be detected
        invalid = validate_columns(["id", "invalid", "title", "foo"])
        assert "invalid" in invalid
        assert "foo" in invalid
        assert "id" not in invalid
        assert "title" not in invalid

    def test_directive_would_raise_on_invalid_column(self) -> None:
        """Test that the doto-list directive validation pattern works.

        This simulates the validation logic that should be used in the
        doto-list directive when processing :columns: option.
        """
        # Simulate directive column validation
        requested_columns = ["id", "title", "invalid_column", "status"]

        invalid_columns = [col for col in requested_columns if col not in VALID_COLUMNS]

        assert invalid_columns == ["invalid_column"], (
            "Validation should detect 'invalid_column' as invalid"
        )

        # This is the error message pattern the directive should use
        if invalid_columns:
            error_msg = (
                f"Invalid column(s): {', '.join(invalid_columns)}. "
                f"Valid columns are: {', '.join(sorted(VALID_COLUMNS))}"
            )
            assert "invalid_column" in error_msg
            assert "id" in error_msg  # id should be in valid columns list
