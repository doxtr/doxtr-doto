"""Pure, render-independent logic for the add-series TUI dialog.

This module owns the *data* / *validation* side of the add-series modal
(:class:`doxtr_doto.cli.tui.app.AddSeriesScreen`) so the logic can be
unit-tested without a live Textual terminal, mirroring
:mod:`doxtr_doto.cli.tui.add_fields` for the add-task modal.

The add-series dialog collects a free-text recurrence *pattern* plus optional
*start time* / *duration* inputs and *from* / *until* dates. The screen assembles
these into a single pattern string and resolves the start/end dates, then hands
the result to :func:`doxtr_doto.cli.tui.actions.add_series` -- the SAME reusable
series-build function the CLI ``doto add --repeat`` path uses -- so the TUI never
duplicates the occurrence/series-building code.

The validation here is deliberately a thin, user-facing wrapper over the
existing CLI parsers so the TUI and CLI accept exactly the same inputs:

* the pattern (with any ``at`` / ``for`` suffix) via
  :func:`doxtr_doto.cli.recurrence.parse_recurrence`,
* the start time via :func:`doxtr_doto.date_utils.parse_time_token`,
* the duration via :func:`doxtr_doto.date_utils.parse_duration`,
* the from/until dates via :func:`doxtr_doto.cli.commands.add.parse_relative_date`.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple


class SeriesFormValues(NamedTuple):
    """The raw text values entered in the add-series dialog.

    Every field is the raw (possibly empty / unstripped) input string, exactly
    as typed. :func:`validate_series_form` turns these into a
    :class:`SeriesFormResult` or a list of error messages.

    Attributes:
        title: The series title template (``{date}`` supported). Required.
        pattern: The recurrence pattern string (e.g. ``every 2 weeks on
            monday``), WITHOUT any ``at`` / ``for`` suffix -- those come from
            the dedicated ``start_time`` / ``duration`` fields and are appended
            by :func:`compose_pattern_str`. Required.
        start_time: Optional start-time token (``16:00`` / ``16h`` /
            ``16:00:31``).
        duration: Optional duration token (``2h`` / ``90m`` / ``1h30m``).
        from_date: Optional series start date (absolute or relative); defaults
            to today when empty.
        until_date: The series end date (absolute or relative). Required.
    """

    title: str
    pattern: str
    start_time: str = ""
    duration: str = ""
    from_date: str = ""
    until_date: str = ""


class SeriesFormResult(NamedTuple):
    """The validated outcome of the add-series dialog.

    The composed ``pattern_str`` is the single carrier of the recurrence spec
    (calendar form plus any ``at`` / ``for`` suffix): the start time and
    duration are validated here for per-field error messages, but are not
    stored separately -- :func:`doxtr_doto.cli.recurrence.parse_recurrence` is
    the single parser that recovers them (along with the calendar portion) from
    ``pattern_str`` on the build side, so the TUI and CLI never diverge.

    Attributes:
        title: The stripped series title template.
        pattern_str: The full pattern string (base pattern plus any ``at`` /
            ``for`` suffix composed from the start-time / duration fields),
            ready for :func:`doxtr_doto.cli.recurrence.parse_recurrence`.
        from_date: The resolved series start date.
        until_date: The resolved series end date.
    """

    title: str
    pattern_str: str
    from_date: date
    until_date: date


def compose_pattern_str(pattern: str, start_time: str, duration: str) -> str:
    """Compose the full pattern string from the base pattern + time/duration.

    Appends `` at <time>`` and/or `` for <duration>`` (in that order) to the
    base pattern when the corresponding field is non-empty, so the result is a
    single string the existing
    :func:`doxtr_doto.cli.recurrence.parse_recurrence` understands. The base
    pattern is used as-is when both extras are empty.

    Args:
        pattern: The base recurrence pattern (no ``at`` / ``for`` suffix).
        start_time: The raw start-time token, or empty.
        duration: The raw duration token, or empty.

    Returns:
        The composed pattern string.
    """
    parts = [pattern.strip()]
    time_token = start_time.strip()
    duration_token = duration.strip()
    if time_token:
        parts.append(f"at {time_token}")
    if duration_token:
        parts.append(f"for {duration_token}")
    return " ".join(p for p in parts if p)


def validate_series_form(
    values: SeriesFormValues,
) -> tuple[SeriesFormResult | None, list[str]]:
    """Validate the raw add-series form values.

    Reuses the exact CLI parsers so the TUI and CLI accept identical inputs.
    Collects *all* field errors (rather than failing on the first) so the modal
    can surface them together. On success the start/until dates are resolved to
    concrete calendar dates and the pattern string is composed from the base
    pattern plus the start-time / duration fields.

    Validation rules (mirroring ``doto add --repeat``):

    * ``title`` and ``pattern`` are required (non-empty after stripping).
    * ``until_date`` is required and must resolve to a valid date.
    * ``from_date`` is optional; empty means today. A time component on the
      from/until dates is dropped (a series start/end is a calendar date).
    * the composed pattern (incl. any ``at`` / ``for`` suffix) must parse.
    * the resolved end date must be strictly after the resolved start date.

    Args:
        values: The raw field values from the dialog.

    Returns:
        A ``(result, errors)`` tuple. On success ``result`` is the
        :class:`SeriesFormResult` and ``errors`` is empty; on failure
        ``result`` is ``None`` and ``errors`` holds one or more user-facing
        messages.
    """
    from doxtr_doto.cli.commands.add import parse_relative_date
    from doxtr_doto.cli.recurrence import parse_recurrence
    from doxtr_doto.date_utils import parse_duration, parse_time_token

    errors: list[str] = []

    title = values.title.strip()
    if not title:
        errors.append("Title is required.")

    base_pattern = values.pattern.strip()
    if not base_pattern:
        errors.append("Repeat pattern is required.")

    start_time_raw = values.start_time.strip()
    if start_time_raw:
        try:
            parse_time_token(start_time_raw)
        except ValueError as err:
            errors.append(f"Invalid start time: {err}")

    duration_raw = values.duration.strip()
    if duration_raw:
        try:
            parse_duration(duration_raw)
        except (ValueError, TypeError) as err:
            errors.append(f"Invalid duration: {err}")

    from_resolved: date | None = None
    from_raw = values.from_date.strip()
    if from_raw:
        try:
            from_resolved = date.fromisoformat(parse_relative_date(from_raw).split("T")[0])
        except ValueError as err:
            errors.append(f"Invalid from date: {err}")
    else:
        from_resolved = date.today()

    until_resolved: date | None = None
    until_raw = values.until_date.strip()
    if not until_raw:
        errors.append("Until date is required.")
    else:
        try:
            until_resolved = date.fromisoformat(parse_relative_date(until_raw).split("T")[0])
        except ValueError as err:
            errors.append(f"Invalid until date: {err}")

    # Compose + validate the full pattern string only when the base pattern was
    # given (so a missing-pattern error is not doubled by a parse error).
    pattern_str = ""
    if base_pattern:
        pattern_str = compose_pattern_str(base_pattern, start_time_raw, duration_raw)
        try:
            parse_recurrence(pattern_str)
        except ValueError as err:
            errors.append(f"Invalid pattern: {err}")

    # End-after-start check only when both dates resolved.
    if from_resolved is not None and until_resolved is not None and until_resolved <= from_resolved:
        errors.append(
            f"Until date ({until_resolved.isoformat()}) must be after "
            f"start date ({from_resolved.isoformat()})."
        )

    if errors:
        return None, errors

    assert from_resolved is not None
    assert until_resolved is not None
    return (
        SeriesFormResult(
            title=title,
            pattern_str=pattern_str,
            from_date=from_resolved,
            until_date=until_resolved,
        ),
        [],
    )
