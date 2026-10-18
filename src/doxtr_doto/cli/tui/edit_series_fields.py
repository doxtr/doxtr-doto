"""Pure, render-independent logic for the edit-series TUI dialog.

This module owns the *data* / *validation* side of the edit-series modal
(:class:`doxtr_doto.cli.tui.app.EditSeriesScreen`) so the logic can be
unit-tested without a live Textual terminal, mirroring
:mod:`doxtr_doto.cli.tui.add_series_fields` for the add-series modal.

The edit-series dialog edits an *existing* series from a selected occurrence
forward. Unlike the add-series dialog it has no *from* / *until* / *apply-to*
fields: the forward-only anchor comes from the selected row (captured by the
app), not typed here. It collects the recurrence *pattern* (base, no ``at`` /
``for`` suffix) plus optional *start time* / *duration* inputs and an optional
*title*.

The validation here is a thin, user-facing wrapper over the SAME CLI parsers
the add-series dialog uses, so the TUI and CLI accept exactly the same inputs:

* the pattern (with any composed ``at`` / ``for`` suffix) via
  :func:`doxtr_doto.cli.recurrence.parse_recurrence`,
* the start time via :func:`doxtr_doto.date_utils.parse_time_token`,
* the duration via :func:`doxtr_doto.date_utils.parse_duration`.

**Clear-vs-keep semantics.** The fields express an *edit* over the stored
series, so blank has a field-specific meaning:

* a blank ``start_time`` / ``duration`` CLEARS that field (the per-occurrence
  time / duration is removed), and
* a blank ``pattern`` / ``title`` KEEPS the stored value unchanged.

Consequently ``title`` and ``pattern`` are NOT required to be non-empty here
(blank simply means "keep"); only a *non-blank* pattern / time / duration is
validated.
"""

from __future__ import annotations

from datetime import time
from typing import NamedTuple

from doxtr_doto.cli.tui.add_series_fields import compose_pattern_str


class EditSeriesFormValues(NamedTuple):
    """The raw text values entered in the edit-series dialog.

    Every field is the raw (possibly empty / unstripped) input string, exactly
    as typed. :func:`validate_edit_series_form` turns these into an
    :class:`EditSeriesFormResult` or a list of error messages.

    Attributes:
        title: The series title template (``{date}`` supported). Blank means
            keep the stored title unchanged.
        pattern: The recurrence pattern string (e.g. ``every 2 weeks on
            monday``), WITHOUT any ``at`` / ``for`` suffix -- those come from
            the dedicated ``start_time`` / ``duration`` fields and are appended
            by :func:`doxtr_doto.cli.tui.add_series_fields.compose_pattern_str`.
            Blank means keep the stored pattern's calendar shape unchanged.
        start_time: Optional start-time token (``16:00`` / ``16h`` /
            ``16:00:31``). Blank CLEARS the per-occurrence start time.
        duration: Optional duration token (``2h`` / ``90m`` / ``1h30m``).
            Blank CLEARS the per-occurrence duration.
    """

    title: str
    pattern: str
    start_time: str = ""
    duration: str = ""


class EditSeriesFormResult(NamedTuple):
    """The validated outcome of the edit-series dialog.

    Attributes:
        title: The stripped title template, or ``None`` when the title field
            was blank (keep the stored title).
        pattern_str: The composed pattern string (base pattern + any ``at`` /
            ``for`` suffix), ready for
            :func:`doxtr_doto.cli.recurrence.parse_recurrence`, or ``None``
            when the pattern field was blank (keep the stored pattern shape).
            When a start time / duration was given alongside a blank base
            pattern, this is ``None`` and the time/duration are carried on the
            :attr:`start_time` / :attr:`duration_minutes` fields instead so the
            caller can apply them over the stored pattern.
        start_time: The parsed start time, or ``None`` when the start-time
            field was blank (CLEAR the time).
        duration_minutes: The parsed duration in whole minutes, or ``None``
            when the duration field was blank (CLEAR the duration).
    """

    title: str | None
    pattern_str: str | None
    start_time: time | None
    duration_minutes: int | None


def validate_edit_series_form(
    values: EditSeriesFormValues,
) -> tuple[EditSeriesFormResult | None, list[str]]:
    """Validate the raw edit-series form values.

    Reuses the exact CLI parsers (and the add-series
    :func:`~doxtr_doto.cli.tui.add_series_fields.compose_pattern_str` helper) so
    the TUI and CLI accept identical inputs. Collects *all* field errors
    (rather than failing on the first) so the modal can surface them together.

    Clear-vs-keep semantics (see the module docstring):

    * blank ``start_time`` / ``duration`` CLEAR that field (result field
      ``None``),
    * blank ``pattern`` / ``title`` KEEP the stored value (result field
      ``None``).

    A non-blank pattern is validated by composing it with any start-time /
    duration tokens and running it through
    :func:`doxtr_doto.cli.recurrence.parse_recurrence`; a non-blank start-time /
    duration is independently validated via
    :func:`doxtr_doto.date_utils.parse_time_token` /
    :func:`doxtr_doto.date_utils.parse_duration` so they surface per-field
    errors even when the base pattern is blank.

    Args:
        values: The raw field values from the dialog.

    Returns:
        A ``(result, errors)`` tuple. On success ``result`` is the
        :class:`EditSeriesFormResult` and ``errors`` is empty; on failure
        ``result`` is ``None`` and ``errors`` holds one or more user-facing
        messages.
    """
    from doxtr_doto.cli.recurrence import parse_recurrence
    from doxtr_doto.date_utils import parse_duration, parse_time_token

    errors: list[str] = []

    title_raw = values.title.strip()
    title = title_raw or None

    start_time_raw = values.start_time.strip()
    start_time: time | None = None
    if start_time_raw:
        try:
            start_time = parse_time_token(start_time_raw)
        except ValueError as err:
            errors.append(f"Invalid start time: {err}")

    duration_raw = values.duration.strip()
    duration_minutes: int | None = None
    if duration_raw:
        try:
            duration_minutes = parse_duration(duration_raw)
        except (ValueError, TypeError) as err:
            errors.append(f"Invalid duration: {err}")

    base_pattern = values.pattern.strip()
    pattern_str: str | None = None
    if base_pattern:
        pattern_str = compose_pattern_str(base_pattern, start_time_raw, duration_raw)
        try:
            parse_recurrence(pattern_str)
        except ValueError as err:
            errors.append(f"Invalid pattern: {err}")

    if errors:
        return None, errors

    return (
        EditSeriesFormResult(
            title=title,
            pattern_str=pattern_str,
            start_time=start_time,
            duration_minutes=duration_minutes,
        ),
        [],
    )
