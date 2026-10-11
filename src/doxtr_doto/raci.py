"""RACI role parsing and formatting.

RACI (Responsible, Accountable, Consulted, Informed) associates people names
with one of four project-management roles on a task.

Public API
----------
* :data:`RACI_ROLES` — canonical role names.
* :data:`RACI_ROLE_LABELS` — canonical ``role -> display label`` mapping.
* :func:`split_names` — split/strip/dedup a comma-separated names string.
* :func:`dedup_names` — order-preserving, case-insensitive name dedup.
* :func:`parse_raci` — parse a comma-separated ``"role name"`` string.
* :func:`format_raci` — format a RACI dict back to the string form.
* :func:`merge_raci` — merge new RACI data into existing RACI data.
* :func:`raci_names` — extract all unique person names from a RACI dict.
* :func:`render_raci_compact` — short summary for list columns (overridable).
* :func:`render_raci_html` — overridable HTML subsection for the task box.
* :func:`register_raci_html_renderer` / :func:`reset_raci_html_renderer` —
  install/reset the HTML renderer seam.
* :func:`register_raci_compact_renderer` / :func:`reset_raci_compact_renderer`
  — install/reset the compact (list-column) renderer seam.
* :func:`filter_raci_differing` — drop roles whose only name is the default
  user (the "boring default"), keeping the non-default spellings.
* :func:`render_raci_differing_lines` — overridable detail-line renderer for
  the TUI card viewer, showing only the RACI entries that differ from the
  configured default user.
* :func:`register_raci_differing_renderer` /
  :func:`reset_raci_differing_renderer` — install/reset that renderer seam.
"""

from __future__ import annotations

from collections.abc import Callable

#: The four canonical RACI roles.
RACI_ROLES: tuple[str, ...] = ("responsible", "accountable", "consulted", "informed")

#: Canonical ``role -> display label`` mapping, derived from :data:`RACI_ROLES`.
#: The single source of truth for human-readable role labels, used by the
#: default HTML renderer and the TUI edit screen's RACI fields.
RACI_ROLE_LABELS: dict[str, str] = {role: role.title() for role in RACI_ROLES}

#: Abbreviation mapping (case-insensitive lookup).
_ROLE_ABBREVS: dict[str, str] = {
    "r": "responsible",
    "a": "accountable",
    "c": "consulted",
    "i": "informed",
}


def _normalize_role(raw: str) -> str | None:
    """Return the canonical role name, or None if unrecognised.

    Accepts full names and single-letter abbreviations, case-insensitively.
    """
    key = raw.strip().lower()
    if key in RACI_ROLES:
        return key
    return _ROLE_ABBREVS.get(key)


def _name_key(name: str) -> str:
    """Return the comparison key for a person name (the single dedup policy).

    This is the single source of truth for how two name spellings are judged
    to be the same person: surrounding whitespace is stripped and the result
    is lower-cased, so ``" Alice "`` and ``"alice"`` share a key. Used by both
    :func:`dedup_names` and :func:`filter_raci_differing` so their
    case-insensitive comparisons cannot drift apart.

    Args:
        name: The candidate name.

    Returns:
        The normalised comparison key.
    """
    return name.strip().lower()


def dedup_names(names: list[str]) -> list[str]:
    """Deduplicate names, order-preserving and case-insensitive.

    This is the single source of truth for the project's name-dedup policy:
    names are compared case-insensitively (so ``"Alice"`` and ``"alice"`` are
    the same person, via :func:`_name_key`) and the *first* spelling
    encountered is kept, preserving input order. Mirrors the known-names
    memory store behavior.

    Args:
        names: The candidate names (already stripped of surrounding
            whitespace).

    Returns:
        The deduplicated names in first-seen order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        key = _name_key(name)
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def split_names(raw: str) -> list[str]:
    """Split a comma-separated names string into a clean, deduped name list.

    Splits on commas, strips surrounding whitespace, drops empty segments, and
    deduplicates via :func:`dedup_names` (order-preserving, case-insensitive).
    This is the single place that defines how a comma-separated RACI/name
    input (CLI ``--raci``, directive ``:raci:``, TUI RACI fields) becomes a
    list of names.

    Args:
        raw: The raw comma-separated string.

    Returns:
        The cleaned, deduplicated list of names (possibly empty).
    """
    return dedup_names([seg.strip() for seg in raw.split(",") if seg.strip()])


def parse_raci(text: str) -> dict[str, list[str]]:
    """Parse a comma-separated ``role name`` string into a RACI dict.

    Format examples::

        "responsible alice, accountable bob, consulted carol, informed dave"
        "r alice, a bob"
        "responsible alice, responsible bob"  → {"responsible": ["alice", "bob"]}

    Role names are case-insensitive.  Single-letter abbreviations (``r``,
    ``a``, ``c``, ``i``) are accepted.

    Args:
        text: The raw RACI string from the directive or CLI option.

    Returns:
        A dict mapping each role to a list of names.  Only roles with at
        least one name are included.

    Raises:
        ValueError: If a segment cannot be parsed (missing role or name) or
            contains an unrecognised role.
    """
    result: dict[str, list[str]] = {}
    if not text or not text.strip():
        return result

    for segment in text.split(","):
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split(None, 1)
        if len(parts) < 2:
            raise ValueError(
                f"Invalid RACI segment '{segment}': expected 'role name' "
                f"(e.g. 'responsible alice')."
            )
        role_raw, name = parts
        role = _normalize_role(role_raw)
        if role is None:
            raise ValueError(
                f"Unknown RACI role '{role_raw}'. "
                f"Valid roles: {', '.join(RACI_ROLES)} (or r/a/c/i)."
            )
        result.setdefault(role, [])
        name = name.strip()
        if name and name.lower() not in {n.lower() for n in result[role]}:
            result[role].append(name)
    return result


def format_raci(raci: dict[str, list[str]] | None) -> str:
    """Format a RACI dict back to the comma-separated ``role name`` string.

    The output order follows :data:`RACI_ROLES` (R-A-C-I).  Each name in a
    role produces a separate ``role name`` pair so the format round-trips
    through :func:`parse_raci`.

    Args:
        raci: RACI dict (may be None or empty).

    Returns:
        The formatted string, or ``""`` when empty/None.
    """
    if not raci:
        return ""
    parts: list[str] = []
    for role in RACI_ROLES:
        for name in raci.get(role, []):
            parts.append(f"{role} {name}")
    return ", ".join(parts)


def merge_raci(
    existing: dict[str, list[str]] | None,
    new: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge *new* RACI data into *existing*, per-role.

    Names in *new* are added to the corresponding role's list (deduped).
    Existing roles not mentioned in *new* are left untouched.

    Args:
        existing: The current RACI dict (may be None).
        new: The incoming RACI data to merge.

    Returns:
        The merged RACI dict.
    """
    merged: dict[str, list[str]] = {}
    if existing:
        for role, names in existing.items():
            merged[role] = list(names)
    for role, names in new.items():
        merged[role] = dedup_names(merged.get(role, []) + list(names))
    return merged


def render_raci_compact(raci: dict[str, list[str]] | None) -> str:
    """Return a short summary like ``R: alice, A: bob`` for list columns.

    Overridable by child themes that register a replacement via
    :func:`register_raci_compact_renderer`.

    Args:
        raci: RACI dict (may be None or empty).

    Returns:
        Compact string, or ``""`` when empty/None.
    """
    return _raci_compact_renderer(raci)


def _default_raci_compact_renderer(raci: dict[str, list[str]] | None) -> str:
    """Built-in RACI compact renderer (``R: alice, A: bob``)."""
    if not raci:
        return ""
    parts: list[str] = []
    for role in RACI_ROLES:
        names = raci.get(role, [])
        if names:
            letter = role[0].upper()
            parts.append(f"{letter}: {', '.join(names)}")
    return ", ".join(parts)


#: Signature of a RACI compact renderer: ``(raci_dict | None) -> str``.
RaciCompactRenderer = Callable[["dict[str, list[str]] | None"], str]

#: THE active RACI compact renderer (modularity seam for child themes).
#: Reassign via :func:`register_raci_compact_renderer`.
_raci_compact_renderer: RaciCompactRenderer = _default_raci_compact_renderer


def register_raci_compact_renderer(fn: RaciCompactRenderer) -> None:
    """Replace the compact renderer used by :func:`render_raci_compact`.

    Args:
        fn: A callable ``(raci_dict | None) -> str``.
    """
    global _raci_compact_renderer
    _raci_compact_renderer = fn


def reset_raci_compact_renderer() -> None:
    """Reset the RACI compact renderer to the built-in default."""
    global _raci_compact_renderer
    _raci_compact_renderer = _default_raci_compact_renderer


def render_raci_html(raci: dict[str, list[str]] | None) -> str:
    """Return an HTML subsection for RACI in the task box.

    Designed to sit below the assignee in the task card.  Overridable by
    child themes that register a replacement via
    :func:`register_raci_html_renderer`.

    Args:
        raci: RACI dict (may be None or empty).

    Returns:
        HTML fragment, or ``""`` when empty/None.
    """
    return _raci_html_renderer(raci)


def _default_raci_html_renderer(raci: dict[str, list[str]] | None) -> str:
    """Built-in RACI HTML renderer."""
    if not raci:
        return ""
    from doxtr_doto.utils import escape_html_content

    lines: list[str] = ['<div class="doto-raci">']
    for role in RACI_ROLES:
        names = raci.get(role, [])
        if names:
            label = RACI_ROLE_LABELS[role]
            escaped = ", ".join(escape_html_content(n) for n in names)
            lines.append(
                f'  <span class="doto-raci-role doto-raci-{role}">'
                f"<strong>{label}:</strong> {escaped}</span>"
            )
    lines.append("</div>")
    return "\n".join(lines)


#: Signature of a RACI HTML renderer: ``(raci_dict | None) -> html``.
RaciHtmlRenderer = Callable[["dict[str, list[str]] | None"], str]

#: THE active RACI HTML renderer (modularity seam for child themes).
#: Reassign via :func:`register_raci_html_renderer`.
_raci_html_renderer: RaciHtmlRenderer = _default_raci_html_renderer


def register_raci_html_renderer(fn: RaciHtmlRenderer) -> None:
    """Replace the RACI HTML renderer used by :func:`render_raci_html`.

    Args:
        fn: A callable ``(raci_dict | None) -> str``.
    """
    global _raci_html_renderer
    _raci_html_renderer = fn


def reset_raci_html_renderer() -> None:
    """Reset the RACI HTML renderer to the built-in default."""
    global _raci_html_renderer
    _raci_html_renderer = _default_raci_html_renderer


def raci_names(raci: dict[str, list[str]] | None) -> list[str]:
    """Extract all unique person names from a RACI dict.

    Args:
        raci: RACI dict (may be None or empty).

    Returns:
        Sorted list of unique names across all roles.
    """
    if not raci:
        return []
    all_names: list[str] = []
    for names in raci.values():
        all_names.extend(names)
    return sorted(dedup_names(all_names), key=lambda s: s.lower())


def filter_raci_differing(
    raci: dict[str, list[str]] | None,
    default_user: str,
) -> dict[str, list[str]]:
    """Return the RACI entries that *differ* from the default user.

    A RACI role assigned only to the configured default user is the "boring
    default" - the person running the tool is naturally responsible for /
    accountable on their own tasks - so it carries no new information and is
    suppressed. This function keeps only the names that are *not* the default
    user, dropping any role left with no remaining names.

    The default-user comparison follows the project's single name-dedup
    policy (:func:`_name_key`, the key used by :func:`dedup_names`): names are
    compared case-insensitively, so ``"Alice"`` and ``"alice"`` are the same
    person. A role listing several people keeps the non-default spellings and
    drops the default-user one (e.g. with default user ``"alice"``,
    ``{"responsible": ["alice", "bob"]}`` becomes
    ``{"responsible": ["bob"]}``). An empty/None ``raci`` short-circuits to an
    empty dict. An empty ``default_user`` means "no default user": with
    nothing to compare against, nothing is suppressed, so every role with at
    least one name is kept, with role order normalised to :data:`RACI_ROLES`
    (R-A-C-I) and any role left with an empty name list dropped.

    Args:
        raci: RACI dict (may be None or empty).
        default_user: The configured default user to treat as the boring
            default. Empty means "no default user": nothing is filtered.

    Returns:
        A new RACI dict (role -> names) with the default-user-only entries
        removed. Role order follows :data:`RACI_ROLES`.
    """
    if not raci:
        return {}
    if not default_user:
        # No default user configured: nothing is the "boring default", so
        # every role/name is kept (role order normalised to R-A-C-I).
        return {role: list(raci[role]) for role in RACI_ROLES if raci.get(role)}
    key = _name_key(default_user)
    result: dict[str, list[str]] = {}
    for role in RACI_ROLES:
        remaining = [n for n in raci.get(role, []) if _name_key(n) != key]
        if remaining:
            result[role] = remaining
    return result


def render_raci_differing_lines(
    raci: dict[str, list[str]] | None,
    default_user: str,
) -> list[str]:
    """Return detail lines for the RACI entries differing from the default user.

    Used by the TUI card viewer
    (:class:`doxtr_doto.cli.tui.app.CardViewerScreen`) to surface *only* the
    RACI roles/names that are not the configured default user - the roles that
    actually tell the reader something, since a role assigned to the person
    running the tool is the uninteresting default (see
    :func:`filter_raci_differing` for the suppression rule and the
    case-insensitive default-user comparison).

    The lines use ``[style]...[/style]`` markup understood by both rich and
    Textual, matching the shared card builder
    (:func:`doxtr_doto.cli.output.build_task_detail_lines`): each kept role
    renders as ``<Label>: <names>`` with the ``RACI_ROLE_LABELS`` label
    and markup-escaped names so a name like ``"[bot] alice"`` renders
    literally. When nothing differs (empty RACI, or every role is only the
    default user) this returns an empty list so the caller adds no lines.

    Overridable by child themes that register a replacement via
    :func:`register_raci_differing_renderer`.

    Args:
        raci: RACI dict (may be None or empty).
        default_user: The configured default user to suppress.

    Returns:
        The detail lines (rich/Textual style markup), or ``[]`` when nothing
        differs from the default user.
    """
    return _raci_differing_renderer(raci, default_user)


def _default_raci_differing_renderer(
    raci: dict[str, list[str]] | None,
    default_user: str,
) -> list[str]:
    """Built-in RACI differing-from-default renderer (``<Label>: ...``)."""
    from doxtr_doto.cli.output import escape_markup

    differing = filter_raci_differing(raci, default_user)
    lines: list[str] = []
    for role, names in differing.items():
        label = RACI_ROLE_LABELS[role]
        rendered = ", ".join(escape_markup(n) for n in names)
        lines.append(f"[bold]{label}:[/bold] {rendered}")
    return lines


#: Signature of a RACI differing renderer: ``(raci_dict | None, user) -> lines``.
RaciDifferingRenderer = Callable[["dict[str, list[str]] | None", str], "list[str]"]

#: THE active RACI differing renderer (modularity seam for child themes).
#: Reassign via :func:`register_raci_differing_renderer`.
_raci_differing_renderer: RaciDifferingRenderer = _default_raci_differing_renderer


def register_raci_differing_renderer(fn: RaciDifferingRenderer) -> None:
    """Replace the renderer used by :func:`render_raci_differing_lines`.

    Args:
        fn: A callable ``(raci_dict | None, default_user) -> list[str]``.
    """
    global _raci_differing_renderer
    _raci_differing_renderer = fn


def reset_raci_differing_renderer() -> None:
    """Reset the RACI differing renderer to the built-in default."""
    global _raci_differing_renderer
    _raci_differing_renderer = _default_raci_differing_renderer
