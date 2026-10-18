"""Line-level three-way (diff3-style) text merge with git-style markers.

The calendar two-way sync needs to reconcile a *doto-owned* event that was
edited on **both** sides since the last sync (locally in the task store and
remotely on the calendar). Field-level merge (whole-value-or-conflict, as in
:mod:`doxtr_doto.sync.merge`) is too coarse for the multi-line ``body`` field:
a user who appended a paragraph locally while someone else appended a different
paragraph remotely should get *both* paragraphs, not a whole-field conflict.

This module provides a small, dependency-free line-level three-way merge
(the classic *diff3* approach) built on :class:`difflib.SequenceMatcher`:

* Lines changed on only one side are taken from that side.
* Hunks changed identically on both sides collapse to the single value.
* Hunks changed differently on both sides are emitted with git-style conflict
  markers (``<<<<<<<`` / ``=======`` / ``>>>>>>>``), so the result is a valid,
  human-resolvable document rather than a silent loss.

It is deliberately generic (no doto types) so it can be unit-tested in
isolation and reused anywhere a textual three-way merge is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

#: Default conflict-marker labels (mirroring git's ``<<<<<<< ours`` style).
LOCAL_LABEL = "local (doto)"
REMOTE_LABEL = "remote (calendar)"


@dataclass
class MergeOutcome:
    """Result of a line-level three-way text merge.

    Attributes:
        text: The merged text (with git-style conflict markers on any hunk that
            diverged on both sides).
        conflicted: True when at least one hunk had to be emitted with conflict
            markers (i.e. both sides changed the same region differently).
    """

    text: str
    conflicted: bool


def _split(text: str) -> list[str]:
    """Split text into lines for merging, preserving no trailing-newline noise.

    We merge on logical lines (``str.splitlines``) and re-join with ``\\n`` so a
    trailing newline difference never shows up as a spurious conflict.
    """
    return (text or "").splitlines()


def merge_three_way(
    base: str,
    local: str,
    remote: str,
    *,
    local_label: str = LOCAL_LABEL,
    remote_label: str = REMOTE_LABEL,
) -> MergeOutcome:
    """Three-way line-level merge of ``local`` and ``remote`` against ``base``.

    Classic diff3: both sides are diffed against the common ancestor ``base``;
    regions changed on only one side take that side, regions changed
    identically collapse, and regions changed on both sides differently are
    wrapped in git-style conflict markers.

    Args:
        base: The common ancestor (last-synced text). May be empty/unknown; an
            empty base makes any non-equal local/remote a conflict (the safe
            diff3 behavior), so callers that have no ancestor still never lose
            text.
        local: The local side's current text.
        remote: The remote side's current text.
        local_label: Label for the ``<<<<<<<`` marker (defaults to the doto
            side).
        remote_label: Label for the ``>>>>>>>`` marker (defaults to the
            calendar side).

    Returns:
        A :class:`MergeOutcome` with the merged text and a conflict flag.
    """
    # Fast paths that also handle the common "only one side changed" cases
    # cleanly without any marker noise.
    if local == remote:
        return MergeOutcome(local, False)
    if local == base:
        return MergeOutcome(remote, False)
    if remote == base:
        return MergeOutcome(local, False)

    base_lines = _split(base)
    local_lines = _split(local)
    remote_lines = _split(remote)

    merged: list[str] = []
    conflicted = False

    for region in _diff3_regions(base_lines, local_lines, remote_lines):
        kind, local_hunk, remote_hunk = region
        if kind == "stable":
            merged.extend(local_hunk)  # == remote_hunk in a stable region
        elif kind == "local":
            merged.extend(local_hunk)
        elif kind == "remote":
            merged.extend(remote_hunk)
        else:  # "conflict"
            conflicted = True
            merged.append(f"<<<<<<< {local_label}")
            merged.extend(local_hunk)
            merged.append("=======")
            merged.extend(remote_hunk)
            merged.append(f">>>>>>> {remote_label}")

    return MergeOutcome("\n".join(merged), conflicted)


def _diff3_regions(
    base: list[str],
    local: list[str],
    remote: list[str],
) -> list[tuple[str, list[str], list[str]]]:
    """Yield merged regions for a diff3 of ``local``/``remote`` against ``base``.

    Each region is ``(kind, local_hunk, remote_hunk)`` where ``kind`` is one of
    ``"stable"`` (unchanged on both sides), ``"local"`` (only local changed),
    ``"remote"`` (only remote changed), or ``"conflict"`` (both changed the same
    base region differently). This walks the two per-side opcode streams in
    lockstep over the shared ``base`` index, the standard way to build a diff3
    from two 2-way diffs.
    """
    local_ops = _changes_by_base(base, local)
    remote_ops = _changes_by_base(base, remote)

    regions: list[tuple[str, list[str], list[str]]] = []
    i = 0  # index into base
    n = len(base)
    while i < n:
        loc = local_ops.get(i)
        rem = remote_ops.get(i)

        if loc is None and rem is None:
            # Unchanged on both sides: emit the single base line, advance by 1.
            regions.append(("stable", [base[i]], [base[i]]))
            i += 1
            continue

        # Determine the base span covered by whichever side(s) changed here.
        span_end = i + 1
        if loc is not None:
            span_end = max(span_end, loc[0])
        if rem is not None:
            span_end = max(span_end, rem[0])

        local_hunk = loc[1] if loc is not None else base[i:span_end]
        remote_hunk = rem[1] if rem is not None else base[i:span_end]

        if loc is not None and rem is not None:
            if local_hunk == remote_hunk:
                regions.append(("local", local_hunk, remote_hunk))  # identical change
            else:
                regions.append(("conflict", local_hunk, remote_hunk))
        elif loc is not None:
            regions.append(("local", local_hunk, base[i:span_end]))
        else:
            regions.append(("remote", base[i:span_end], remote_hunk))

        i = span_end

    # Trailing inserts past the end of base (append-only edits on either side).
    tail_local = local_ops.get(n)
    tail_remote = remote_ops.get(n)
    if tail_local is not None or tail_remote is not None:
        lh = tail_local[1] if tail_local is not None else []
        rh = tail_remote[1] if tail_remote is not None else []
        if tail_local is not None and tail_remote is not None:
            if lh == rh:
                regions.append(("local", lh, rh))
            else:
                regions.append(("conflict", lh, rh))
        elif tail_local is not None:
            regions.append(("local", lh, []))
        else:
            regions.append(("remote", [], rh))

    return regions


def _changes_by_base(base: list[str], other: list[str]) -> dict[int, tuple[int, list[str]]]:
    """Map a base line index -> (base_end, replacement_lines) for each edit.

    Uses :class:`difflib.SequenceMatcher` opcodes to describe how ``other``
    differs from ``base``. Each non-``equal`` opcode becomes an entry keyed by
    its base start index, recording the base end index and the lines ``other``
    put there (empty list for a pure deletion). Pure insertions (``base`` start
    == end) are keyed by that index too, including the special index
    ``len(base)`` for an append past the end.
    """
    out: dict[int, tuple[int, list[str]]] = {}
    sm = SequenceMatcher(a=base, b=other, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        out[i1] = (i2, other[j1:j2])
    return out
