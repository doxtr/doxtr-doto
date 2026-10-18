"""Central registry of all DotoTask fields.

All modules that need to enumerate task fields import from here.
Registering a ``FieldDefinition`` below auto-propagates the field to the
derived collections (merge, display columns, serialization, labels) and the
``BY_*`` lookup maps. A new field, however, is NOT fully wired by the registry
alone -- these additional touch-points must be updated by hand (a type checker
will not flag them as stale):

* :class:`doxtr_doto.collectors.DotoTask` -- add the attribute and include it
  in ``to_dict`` / ``from_dict`` / ``to_sync_dict``.
* :class:`doxtr_doto.sync.json_store.TaskData` -- add the TypedDict key.
* :func:`doxtr_doto.sync.json_store` schema migration -- backfill the key and
  bump ``SCHEMA_VERSION``.
* :func:`doxtr_doto.directives.doto.DotoDirective` -- add the option and parse
  it, if the field is author-settable.
* Rendering seams, if the field is ``displayable``:
  :func:`doxtr_doto.nodes._get_task_column_value` (docutils HTML/LaTeX path)
  and :func:`doxtr_doto.template_loader._column_value_filter` (Jinja path).
* Sorting, if the field should be sortable:
  ``directives.doto_list.VALID_SORT_FIELDS`` plus the ``sort_key`` functions in
  :func:`doxtr_doto.collectors._filter_tasks_impl` and
  :func:`doxtr_doto.cli.commands.list`.

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
        resolves_xlinks: Whether render-time ``:xlink:`key``` resolution runs on
            this field's value. Only enable for free-text fields whose value is
            rendered as plain text (not reST-parsed) so a resolved display name
            / link renders cleanly. See :data:`XLINK_FIELDS`.
        default: Default value for new tasks.
    """

    name: str
    rst_name: str
    json_name: str
    display_label: str
    mergeable: bool = True
    displayable: bool = True
    serializable: bool = True
    resolves_xlinks: bool = False
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
        resolves_xlinks=True,
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
        # Stored as a single string: ``YYYY-MM-DD`` (date-only) OR
        # ``YYYY-MM-DDTHH:MM[:SS]`` when the due carries an optional naive-local
        # time. Parsing/formatting is centralized in
        # :mod:`doxtr_doto.date_utils`; see the "Due dates with time" README
        # section.
        default=None,
    ),
    FieldDefinition(
        name="estimate",
        rst_name="estimate",
        json_name="estimate",
        display_label="Estimate",
        mergeable=True,
        displayable=True,
        # Expected duration the task should take, stored as a whole number of
        # minutes (``int``). Authored with the compact duration syntax (``5m``,
        # ``4h``, ``1h30m``); parsing/formatting is centralized in
        # :mod:`doxtr_doto.date_utils` (``parse_duration`` /
        # ``format_duration_minutes``). Consumed by calendar-sync to size the
        # projected event, overriding the global ``event_duration_minutes``.
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
        name="raci",
        rst_name="raci",
        json_name="raci",
        display_label="RACI",
        mergeable=True,
        displayable=True,
        serializable=True,
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
DISPLAY_COLUMNS: tuple[str, ...] = tuple(f.rst_name for f in TASK_FIELDS if f.displayable)

# Valid column names for doto-list directive (includes 'id' which is not a field)
VALID_COLUMNS: frozenset[str] = frozenset(DISPLAY_COLUMNS) | {"id"}

# Fields that are serialized to JSON
SERIALIZABLE_FIELDS: tuple[str, ...] = tuple(f.name for f in TASK_FIELDS if f.serializable)

# Fields whose rendered value has render-time ``:xlink:`key``` resolution applied
# (see FieldDefinition.resolves_xlinks). Keyed by ``rst_name`` because every
# render seam compares against the lower-cased column/``rst_name`` key.
#
# Decision (xlink-fixes A1): only ``assignee`` resolves. ``title`` is rendered in
# the task-box header, list cells AND as cross-reference link text, so resolving
# it would need several extra seams and could leak a resolved name into a ref
# label; it is left off as the brief marks it optional. ``body`` stays off
# because it is parsed as reST (not plain text), where a resolved literal would
# not render cleanly. The flag is data-driven, so enabling another plain-text
# field is a one-line change here with no render-code edits.
XLINK_FIELDS: frozenset[str] = frozenset(f.rst_name for f in TASK_FIELDS if f.resolves_xlinks)

# Lookup maps for accessing field definitions by different key types
BY_NAME: dict[str, FieldDefinition] = {f.name: f for f in TASK_FIELDS}
BY_RST_NAME: dict[str, FieldDefinition] = {f.rst_name: f for f in TASK_FIELDS}
BY_JSON_NAME: dict[str, FieldDefinition] = {f.json_name: f for f in TASK_FIELDS}

# Field name mapping from Python names to RST names (only where they differ)
FIELD_NAME_TO_RST: dict[str, str] = {
    f.name: f.rst_name for f in TASK_FIELDS if f.name != f.rst_name
}

# Column labels for table headers (RST name -> display label)
COLUMN_LABELS: dict[str, str] = {"id": "ID"} | {f.rst_name: f.display_label for f in TASK_FIELDS}
