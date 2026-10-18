"""Resolve a persisted calendar-sync conflict on a task.

When a two-way merge (``conflict_policy = "merge"``) finds the *same* field
changed on both the local task and its calendar event, it writes the diff3
\"keep both\" value (git-style ``<<<<<<<`` markers for the body) and records the
three candidate values per field under ``task["_sync"]["conflict"]``. This
module turns that stash into a simple, re-usable resolution step so the user is
never stuck hand-deleting markers:

* :data:`ResolutionChoice` -- keep **local**, keep **remote**, or keep **both**.
* :func:`resolve_conflict` -- apply a choice to a task dict, returning the field
  updates to persist (and clearing the ``sync_conflict`` flag + stash).

The same helper backs both the CLI (``doto calsync resolve``) and the TUI
resolution dialog, so the two can never drift. Resolving only touches the local
task; the next push re-converges the calendar from the resolved value.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

#: Conflict-marker lines written by the diff3 body merge (see
#: :mod:`doxtr_doto.calsync.textmerge`). The labels after the markers are
#: cosmetic, so the patterns match the marker prefix and ignore the label.
_MARKER_LOCAL = re.compile(r"^<<<<<<<.*$")
_MARKER_SEP = re.compile(r"^=======\s*$")
_MARKER_REMOTE = re.compile(r"^>>>>>>>.*$")


class ResolutionChoice(str, Enum):
    """How to resolve a conflicted field.

    * ``LOCAL`` -- keep the local task's value, discard the remote edit.
    * ``REMOTE`` -- take the calendar's value, discard the local edit.
    * ``BOTH`` -- keep both (the diff3-merged body with markers, or the joined
      scalar), so nothing is lost and the user trims it in the editor.
    """

    LOCAL = "local"
    REMOTE = "remote"
    BOTH = "both"


def get_conflict(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a task's persisted sync-conflict stash, or None when there is none.

    The stash lives at ``task["_sync"]["conflict"]`` and is a dict of the form
    ``{"detected": iso, "fields": [{"field", "base", "local", "remote",
    "both"}, ...]}``. Returns None when the task carries no unresolved conflict.
    """
    sync = task.get("_sync")
    if not isinstance(sync, dict):
        return None
    conflict = sync.get("conflict")
    if not isinstance(conflict, dict):
        return None
    return conflict


def conflict_fields(task: dict[str, Any]) -> list[dict[str, str]]:
    """Return the per-field conflict records for a task (empty when none).

    Prefers the structured ``_sync.conflict`` stash written by a recent merge.
    As a **fallback**, if the stash is absent but the body still carries
    git-style conflict markers (e.g. a task merged before the stash existed, or
    a hand-edited body), the body conflict is reconstructed from those markers
    so it is still resolvable. The reconstructed record's ``base`` is unknown
    (empty); ``local``/``remote`` are the two marked hunks spliced back into
    the surrounding text, and ``both`` is the body verbatim (markers intact).
    """
    conflict = get_conflict(task)
    if conflict is not None:
        fields = conflict.get("fields")
        if isinstance(fields, list) and fields:
            return list(fields)
    # Fallback: reconstruct a body conflict from git-style markers.
    body = str(task.get("body") or "")
    record = _body_conflict_from_markers(body)
    return [record] if record is not None else []


def _body_conflict_from_markers(body: str) -> dict[str, str] | None:
    """Reconstruct a body :class:`FieldConflict`-shaped record from markers.

    Parses one or more ``<<<<<<< / ======= / >>>>>>>`` conflict blocks and
    produces the local-only and remote-only variants of the whole body (each
    block replaced by its respective side), plus the verbatim "both" text.
    Returns None when the body has no (balanced) conflict markers.
    """
    lines = body.splitlines()
    # Quick reject: need at least one complete marker triple.
    if not any(_MARKER_LOCAL.match(ln) for ln in lines):
        return None

    local_out: list[str] = []
    remote_out: list[str] = []
    i = 0
    saw_block = False
    n = len(lines)
    while i < n:
        line = lines[i]
        if _MARKER_LOCAL.match(line):
            # Collect the local hunk until the separator.
            i += 1
            local_hunk: list[str] = []
            while i < n and not _MARKER_SEP.match(lines[i]):
                if _MARKER_REMOTE.match(lines[i]):
                    break
                local_hunk.append(lines[i])
                i += 1
            # Separator.
            if i < n and _MARKER_SEP.match(lines[i]):
                i += 1
            # Remote hunk until the closing marker.
            remote_hunk: list[str] = []
            while i < n and not _MARKER_REMOTE.match(lines[i]):
                remote_hunk.append(lines[i])
                i += 1
            # Closing marker.
            if i < n and _MARKER_REMOTE.match(lines[i]):
                i += 1
            local_out.extend(local_hunk)
            remote_out.extend(remote_hunk)
            saw_block = True
        else:
            local_out.append(line)
            remote_out.append(line)
            i += 1

    if not saw_block:
        return None
    return {
        "field": "body",
        "base": "",
        "local": "\n".join(local_out).strip("\n"),
        "remote": "\n".join(remote_out).strip("\n"),
        "both": body,
    }


def resolve_conflict(
    task: dict[str, Any],
    choice: ResolutionChoice,
    *,
    field: str | None = None,
) -> dict[str, Any]:
    """Compute the field updates that resolve a task's sync conflict.

    Args:
        task: The task dict carrying the ``_sync.conflict`` stash.
        choice: Which side to keep (:class:`ResolutionChoice`).
        field: Resolve only this field when given; otherwise resolve every
            conflicted field. A field with no stashed conflict is ignored.

    Returns:
        A dict of ``{field: value, ...}`` updates to apply to the task. When
        *every* conflicted field is resolved (``field`` is None, or it was the
        only conflicted field) the result also clears the ``sync_conflict``
        flag and the ``_sync.conflict`` stash. When only one of several fields
        is resolved, the stash is rewritten to keep the remaining ones.

    Raises:
        ValueError: If the task has no recorded conflict, or ``field`` is given
            but not among the conflicted fields.
    """
    records = conflict_fields(task)
    if not records:
        raise ValueError("Task has no recorded calendar-sync conflict to resolve.")

    by_field = {str(r.get("field")): r for r in records}
    if field is not None and field not in by_field:
        raise ValueError(
            f"Field {field!r} is not in conflict. Conflicted fields: " + ", ".join(sorted(by_field))
        )

    targets = [field] if field is not None else list(by_field)
    updates: dict[str, Any] = {}
    for fname in targets:
        record = by_field[fname]
        updates[fname] = _value_for_choice(record, choice)

    remaining = [r for r in records if str(r.get("field")) not in targets]
    if remaining:
        # Partial resolution: keep the still-unresolved fields in the stash.
        conflict = get_conflict(task) or {}
        updates["_sync"] = {
            "conflict": {
                "detected": conflict.get("detected"),
                "fields": remaining,
            }
        }
        updates["sync_conflict"] = True
    else:
        # Everything resolved: clear the flag and the stash.
        updates["sync_conflict"] = False
        updates["_sync"] = {"conflict": None}
    return updates


def _value_for_choice(record: dict[str, str], choice: ResolutionChoice) -> str:
    """Return the field value a resolution ``choice`` selects from a record."""
    if choice is ResolutionChoice.LOCAL:
        return str(record.get("local", ""))
    if choice is ResolutionChoice.REMOTE:
        return str(record.get("remote", ""))
    return str(record.get("both", ""))


def conflict_preview(record: dict[str, str]) -> tuple[str, str]:
    """Return ``(local, remote)`` previews focused on where the sides differ.

    When both sides share a long common prefix/suffix (typical for a body whose
    conflict is a single changed paragraph), a naive head-of-string preview
    shows only the identical text. This trims the shared prefix and suffix so
    the preview highlights the *conflicting* content, falling back to the whole
    value when the sides differ from the start.
    """
    local = " ".join(str(record.get("local", "")).split())
    remote = " ".join(str(record.get("remote", "")).split())
    if local == remote:
        return local, remote
    # Trim the shared leading prefix (on a word boundary-ish char index).
    start = 0
    max_common = min(len(local), len(remote))
    while start < max_common and local[start] == remote[start]:
        start += 1
    # Trim the shared trailing suffix.
    end_l, end_r = len(local), len(remote)
    while end_l > start and end_r > start and local[end_l - 1] == remote[end_r - 1]:
        end_l -= 1
        end_r -= 1
    local_diff = local[start:end_l].strip() or "(empty)"
    remote_diff = remote[start:end_r].strip() or "(empty)"
    prefix = "\u2026" if start > 0 else ""
    return f"{prefix}{local_diff}", f"{prefix}{remote_diff}"
