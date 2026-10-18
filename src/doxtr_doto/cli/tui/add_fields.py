"""Pure, render-independent logic for the configurable add-task modal.

This module owns the *data* side of the add-task modal (which fields are
shown, in what order, and their resolved per-field default values) so the
logic can be unit-tested without a live Textual terminal. The rendering side
(:class:`doxtr_doto.cli.tui.app.AddTaskScreen`) consumes the helpers here.

Three named field-set *presets* select which task fields the modal exposes:

* ``minimal`` -- ``title`` only (plus the repo selector when >1 repo). This is
  the backward-compatible default and behaves EXACTLY as the original
  title-only add modal.
* ``default`` -- ``title``, ``tags``, ``due``, ``assignee``, ``body`` (plus the
  repo selector), in that order.
* ``all`` -- every user-settable field, derived DYNAMICALLY from the canonical
  :data:`doxtr_doto.fields.TASK_FIELDS` registry (so a newly registered field
  appears automatically), excluding the computed/non-settable ``created`` and
  ``updated`` fields. RACI renders as its role sub-fields.

The selected preset / explicit field list comes from config
(``tui_add_fields``) and per-field defaults from ``tui_add_defaults``; see
:func:`resolve_field_names` for the precedence rules.

Note (new-field caveat): registering a new settable field in
:data:`doxtr_doto.fields.TASK_FIELDS` makes it appear in the ``all`` preset and
render in the modal automatically, but *persisting* its entered value also
requires wiring the fixed create pipeline by hand -
:class:`doxtr_doto.cli.tui.app.AddTaskResult`,
:meth:`doxtr_doto.cli.tui.app.AddTaskScreen.collect_result`,
:meth:`doxtr_doto.cli.tui.app.DotoApp.action_add`,
:func:`doxtr_doto.cli.tui.actions.add_task` and
:func:`doxtr_doto.cli.commands.add._build_task_data` - consistent with the
manual touch-points the :mod:`doxtr_doto.fields` module docstring lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from doxtr_doto.fields import BY_NAME, TASK_FIELDS

if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig

#: Fields excluded from the dynamically-derived ``all`` preset because they are
#: computed/stamped by the store rather than set by the user at creation time.
#: Kept data-driven so the ``all`` preset stays in sync with the registry: any
#: new field in :data:`doxtr_doto.fields.TASK_FIELDS` that is not listed here is
#: automatically offered in the add modal's ``all`` preset.
NON_SETTABLE_FIELDS: frozenset[str] = frozenset({"created", "updated"})

#: The pseudo-field name for the target-repository selector. It is NOT a task
#: field (not in :data:`doxtr_doto.fields.TASK_FIELDS`); it selects which
#: repository a new task is created in. It is accepted as a special, orderable
#: entry in an *explicit* ``tui_add_fields`` list so the repository picker can
#: be positioned anywhere in the modal (rather than its implicit
#: "right after title" placement used by the presets). When present it renders
#: the selector at its configured position instead of after the title.
REPO_FIELD = "repo"

#: The fixed ``default`` preset field order (title first). The repo selector is
#: handled separately by the modal and always follows the title when >1 repo.
DEFAULT_PRESET_FIELDS: tuple[str, ...] = (
    "title",
    "tags",
    "due",
    "assignee",
    "body",
)

#: The ``minimal`` preset: title only. Backward-compatible default.
MINIMAL_PRESET_FIELDS: tuple[str, ...] = ("title",)

#: The preset name used when ``tui_add_fields`` is unset, unknown, or invalid.
DEFAULT_PRESET_NAME = "minimal"


def all_preset_fields() -> tuple[str, ...]:
    """Return the ``all`` preset's field list, derived from the registry.

    Every field in :data:`doxtr_doto.fields.TASK_FIELDS` is included in
    registry order except those named in :data:`NON_SETTABLE_FIELDS`
    (``created`` / ``updated``). Deriving this dynamically means registering a
    new settable field in :mod:`doxtr_doto.fields` automatically surfaces it in
    the add modal's ``all`` preset with no change here.

    Returns:
        The ordered tuple of user-settable field names (``title`` first,
        matching registry order).
    """
    return tuple(f.name for f in TASK_FIELDS if f.name not in NON_SETTABLE_FIELDS)


def preset_fields(name: str) -> tuple[str, ...] | None:
    """Return the field list for a named preset, or None if unknown.

    Args:
        name: The preset name (case-insensitively ``minimal`` / ``default`` /
            ``all``).

    Returns:
        The ordered field-name tuple for the preset, or None when ``name`` is
        not a recognized preset.
    """
    key = name.strip().lower()
    if key == "minimal":
        return MINIMAL_PRESET_FIELDS
    if key == "default":
        return DEFAULT_PRESET_FIELDS
    if key == "all":
        return all_preset_fields()
    return None


def resolve_field_names(spec: str | list[str] | None) -> tuple[str, ...]:
    """Resolve the configured ``tui_add_fields`` value to an ordered field list.

    Precedence / interpretation:

    1. An explicit *list* of field names overrides any preset. Unknown field
       names (not in :data:`doxtr_doto.fields.BY_NAME`) and non-settable fields
       (:data:`NON_SETTABLE_FIELDS`) are dropped silently so a typo never
       crashes the TUI. The one allowed non-registry name is :data:`REPO_FIELD`
       (``"repo"``): the repository-selector pseudo-field, which is kept at its
       configured position so the picker can be placed anywhere in the modal.
       ``title`` is always included: if omitted it is prepended at index 0,
       which pushes any explicitly-placed ``repo`` down by one
       (e.g. ``["repo", "body"]`` resolves to ``("title", "repo", "body")``);
       when ``title`` is listed, every entry keeps its given order
       (``["repo", "title", ...]`` stays ``("repo", "title", ...)``).
    2. A *string* names a preset (``minimal`` / ``default`` / ``all``). An
       unknown preset name falls back to the :data:`DEFAULT_PRESET_NAME`
       (``minimal``).
    3. ``None`` / empty falls back to the ``minimal`` preset (backward
       compatible: title only).

    The returned order is the exact top-to-bottom render order the modal uses.

    Args:
        spec: The configured ``tui_add_fields`` value: a preset name string, an
            explicit list of field names, or None.

    Returns:
        The ordered tuple of field names to render (always starting with
        ``title``).
    """
    if isinstance(spec, list):
        names: list[str] = []
        for raw in spec:
            name = str(raw).strip()
            if not name:
                continue
            # ``repo`` is the one allowed non-registry name: the repository
            # selector pseudo-field, kept at its configured position.
            if name != REPO_FIELD and (name not in BY_NAME or name in NON_SETTABLE_FIELDS):
                continue
            if name not in names:
                names.append(name)
        if "title" not in names:
            names.insert(0, "title")
        return tuple(names)

    if isinstance(spec, str) and spec.strip():
        fields = preset_fields(spec)
        if fields is not None:
            return fields

    return MINIMAL_PRESET_FIELDS


def resolve_default(
    field_name: str,
    defaults: dict[str, str],
    config: DotoConfig,
) -> str:
    """Return the resolved string default for a single text/input field.

    Resolution order for each field:

    1. An entry in the ``tui_add_defaults`` table (``defaults``) wins.
    2. For ``assignee`` / ``priority`` / ``status`` the existing config
       defaults (``default_assignee`` / ``default_priority`` /
       ``default_status``) are the fallback, preserving current behavior.
    3. Otherwise an empty string (no prefill).

    Date fields (``due``) support dynamic relative expressions (``tomorrow``,
    ``+7d``, ``friday``) resolved *here* via the same
    :func:`doxtr_doto.cli.commands.add.parse_relative_date` helper the CLI and
    edit modal use. An unparseable date falls back to an empty string (the bad
    default never surfaces an error at modal open).

    Args:
        field_name: The field whose default to resolve (e.g. ``"assignee"``).
        defaults: The ``tui_add_defaults`` mapping (field name -> raw value).
        config: The active config, for the ``default_*`` fallbacks.

    Returns:
        The resolved string value to prefill the field with (possibly empty).
    """
    raw = defaults.get(field_name)

    if raw is None or not str(raw).strip():
        # Fall back to the existing config defaults for the classic fields.
        if field_name == "assignee":
            return config.default_assignee or ""
        if field_name == "priority":
            return config.default_priority or ""
        if field_name == "status":
            return config.default_status or ""
        return ""

    value = str(raw).strip()

    if field_name == "due":
        return _resolve_date_default(value)

    return value


def _resolve_date_default(value: str) -> str:
    """Resolve a date-field default (absolute or relative) to a concrete date.

    Reuses :func:`doxtr_doto.cli.commands.add.parse_relative_date` so relative
    expressions (``tomorrow``, ``+7d``, ``friday``) resolve the same way they
    do in the CLI and edit modal. An unparseable value silently falls back to
    an empty string, so a bad date default never raises at modal open.

    Args:
        value: The raw (already-stripped, non-empty) date default.

    Returns:
        The resolved ``YYYY-MM-DD`` (or ``YYYY-MM-DDTHH:MM``) string, or an
        empty string when the value cannot be parsed.
    """
    from doxtr_doto.cli.commands.add import parse_relative_date

    try:
        return parse_relative_date(value)
    except ValueError:
        return ""
