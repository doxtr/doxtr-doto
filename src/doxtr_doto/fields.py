"""Central registry of all DotoTask fields.

All modules that need to enumerate task fields import from here.
Adding a new field requires changes in exactly one place (plus
the DotoTask dataclass and JSON schema migration).

This module provides:
- FieldDefinition: Dataclass describing a single task field
- TASK_FIELDS: Canonical ordered tuple of all field definitions
- Derived convenience collections for merge, display, and serialization
- Lookup maps for accessing fields by different key types
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldDefinition:
    """Metadata for a single task field.

    Attributes:
        name: Internal Python attribute name (uses underscores).
        rst_name: Option name in the RST directive (uses hyphens).
        json_name: Key name in tasks.json.
        display_label: Human-readable column header.
        mergeable: Whether this field participates in 3-way merge.
        displayable: Whether this field can appear as a table column.
        serializable: Whether this field is written to JSON.
        default: Default value for new tasks.
    """

    name: str
    rst_name: str
    json_name: str
    display_label: str
    mergeable: bool = True
    displayable: bool = True
    serializable: bool = True
    default: Any = None


# Canonical ordered list of all task fields.
# Adding a field here automatically propagates it to:
#   - MERGE_FIELDS (sync/merge.py)
#   - column validation (directives/doto_list.py)
#   - table rendering  (nodes.py)
#   - directive generation (sync/rst_writer.py)
#   - JSON serialization (collectors/__init__.py)
TASK_FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="title",
        rst_name="title",
        json_name="title",
        display_label="Title",
        mergeable=True,
        displayable=True,
    ),
    FieldDefinition(
        name="assignee",
        rst_name="assignee",
        json_name="assignee",
        display_label="Assignee",
        mergeable=True,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="priority",
        rst_name="priority",
        json_name="priority",
        display_label="Priority",
        mergeable=True,
        displayable=True,
        default="medium",
    ),
    FieldDefinition(
        name="status",
        rst_name="status",
        json_name="status",
        display_label="Status",
        mergeable=True,
        displayable=True,
        default="open",
    ),
    FieldDefinition(
        name="due",
        rst_name="due",
        json_name="due",
        display_label="Due Date",
        mergeable=True,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="tags",
        rst_name="tags",
        json_name="tags",
        display_label="Tags",
        mergeable=True,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="depends_on",
        rst_name="depends-on",
        json_name="depends_on",
        display_label="Dependencies",
        mergeable=True,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="body",
        rst_name="body",
        json_name="body",
        display_label="Description",
        mergeable=True,
        displayable=False,
    ),
    FieldDefinition(
        name="progress",
        rst_name="progress",
        json_name="progress",
        display_label="Progress",
        mergeable=True,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="created",
        rst_name="created",
        json_name="created",
        display_label="Created",
        mergeable=False,
        displayable=True,
        default=None,
    ),
    FieldDefinition(
        name="updated",
        rst_name="updated",
        json_name="updated",
        display_label="Updated",
        mergeable=False,
        displayable=True,
        default=None,
    ),
)

# Derived convenience collections — computed once at module load

# Fields that participate in the 3-way merge algorithm
MERGE_FIELDS: tuple[str, ...] = tuple(f.name for f in TASK_FIELDS if f.mergeable)

# Fields that can appear as table columns (RST names for directive validation)
DISPLAY_COLUMNS: tuple[str, ...] = tuple(
    f.rst_name for f in TASK_FIELDS if f.displayable
)

# Valid column names for doto-list directive (includes 'id' which is not a field)
VALID_COLUMNS: frozenset[str] = frozenset(DISPLAY_COLUMNS) | {"id"}

# Fields that are serialized to JSON
SERIALIZABLE_FIELDS: tuple[str, ...] = tuple(
    f.name for f in TASK_FIELDS if f.serializable
)

# Lookup maps for accessing field definitions by different key types
BY_NAME: dict[str, FieldDefinition] = {f.name: f for f in TASK_FIELDS}
BY_RST_NAME: dict[str, FieldDefinition] = {f.rst_name: f for f in TASK_FIELDS}
BY_JSON_NAME: dict[str, FieldDefinition] = {f.json_name: f for f in TASK_FIELDS}

# Field name mapping from Python names to RST names (only where they differ)
FIELD_NAME_TO_RST: dict[str, str] = {
    f.name: f.rst_name for f in TASK_FIELDS if f.name != f.rst_name
}

# Column labels for table headers (RST name -> display label)
COLUMN_LABELS: dict[str, str] = {"id": "ID"} | {
    f.rst_name: f.display_label for f in TASK_FIELDS
}
