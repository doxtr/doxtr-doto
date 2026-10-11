"""Restore an archived doto task back to its original place in an RST file.

When a task is archived, its directive is removed from the source RST file and
a positional "restore anchor" is captured into the task's JSON ``_sync`` block
(see :func:`doxtr_doto.sync.rst_writer.capture_restore_anchor`). When the task
is later reopened, :func:`restore_task_to_rst` uses that anchor to decide where
to re-insert the directive:

* ``ANCHOR`` \u2014 the anchor's preceding context is still present and unambiguous
  in the current file, so the directive is re-inserted at that exact location.
* ``TOP_OF_PAGE`` \u2014 the file still exists but the anchor no longer matches
  (the preceding context changed, is missing, or now appears more than once).
  This is the "heavily modified file" fallback: the directive is inserted at
  the TOP of the page, directly under the first heading, so it is not lost.
* ``PAGE_MISSING`` \u2014 the original RST file no longer exists (the page was
  renamed or deleted). The directive is NOT relocated to the inbox; instead the
  restore fails for this task with a clear message naming the original page
  title and path so the user can retrace where it was.

The "heavily modified file" rule is defined precisely as: the recorded run of
preceding non-blank source lines either does not appear in the current file, or
appears more than once (ambiguous). Either case yields ``TOP_OF_PAGE``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from doxtr_doto.sync.rst_writer import (
    find_anchor_insertion_line,
    find_title_insertion_line,
    insert_directive_into_content,
)
from doxtr_doto.utils import validate_path_within

logger = logging.getLogger(__name__)

#: Current ``_archive`` schema version this module writes/understands. A
#: captured anchor with a missing or unknown version is treated as version 1
#: for back-compatibility (see :func:`restore_task_to_rst`).
_CURRENT_ARCHIVE_VERSION = 1


class RestorePath(str, Enum):
    """Which restore strategy was taken by :func:`restore_task_to_rst`."""

    #: Directive re-inserted at its original anchored location.
    ANCHOR = "anchor"
    #: Anchor missing/ambiguous: directive inserted at the top of the page.
    TOP_OF_PAGE = "top_of_page"
    #: Original page renamed/deleted: restore failed, no relocation.
    PAGE_MISSING = "page_missing"


@dataclass
class RestoreResult:
    """Outcome of a restore-to-place operation.

    Attributes:
        success: True if the directive was written back to a file.
        path: Which :class:`RestorePath` strategy was taken.
        rst_file: The RST file (relative) the task was restored into, or the
            original file that was missing.
        message: Human-readable message. For ``PAGE_MISSING`` this is the
            error naming the original page title and path.
        page_title: Captured original page title (if any), surfaced for callers.
    """

    success: bool
    path: RestorePath
    rst_file: str | None = None
    message: str = ""
    page_title: str | None = None


# =============================================================================
# Pluggable anchor/restore strategy seam
# =============================================================================
#
# A restore strategy decides, for a given file, (a) where an anchored directive
# should be re-inserted and (b) where the top-of-page fallback should land. The
# two callables mirror the built-in rst_writer helpers:
#
#   find_anchor(content, preceding_lines) -> int | None  (1-indexed, insert-after)
#   find_title(content)                   -> int | None  (1-indexed underline line)
#
# This exists so a downstream project can register an alternative
# anchor-capture / heavily-modified-detection strategy WITHOUT editing core
# (mirrors template_loader._FALLBACK_RENDERERS). Strategies are keyed in
# _RESTORE_STRATEGIES by the ``_archive`` block's integer ``version`` and/or an
# explicit string ``strategy`` name; the built-in is registered as the default
# (version 1 and name "builtin"). See register_restore_strategy.

#: Signature of a strategy's anchor finder: (content, preceding_lines) -> line.
_AnchorFinder = Callable[[str, list[str]], "int | None"]
#: Signature of a strategy's title finder: (content) -> underline line.
_TitleFinder = Callable[[str], "int | None"]


@dataclass(frozen=True)
class RestoreStrategy:
    """A pluggable pair of callables driving restore anchor placement.

    Attributes:
        find_anchor: Returns the 1-indexed line to insert after when the
            captured anchor still matches uniquely, else None (heavily
            modified => top-of-page).
        find_title: Returns the 1-indexed section-underline line of the first
            heading, so the top-of-page fallback lands under the title, or None
            when the file has no heading (caller prepends at document start).
    """

    find_anchor: _AnchorFinder
    find_title: _TitleFinder


#: Registry of restore strategies keyed by ``_archive`` ``version`` (int) and
#: by strategy ``name`` (str). The built-in default is registered under both
#: :data:`_CURRENT_ARCHIVE_VERSION` and the name ``"builtin"``.
_RESTORE_STRATEGIES: dict[Any, RestoreStrategy] = {}


def register_restore_strategy(
    key: int | str,
    strategy: RestoreStrategy,
) -> None:
    """Register a restore strategy under an ``_archive`` version or name.

    Downstream extension point: a child project can register an alternative
    anchor-capture / heavily-modified-detection strategy and have archived
    tasks whose ``_archive`` block carries the matching ``version`` (int key)
    or ``strategy`` name (str key) restored through it, without editing core.

    Args:
        key: The ``_archive`` ``version`` (int) or ``strategy`` name (str) this
            strategy handles.
        strategy: The :class:`RestoreStrategy` to use for that key.
    """
    _RESTORE_STRATEGIES[key] = strategy


#: The built-in restore strategy: the original rst_writer anchor/title finders.
_BUILTIN_STRATEGY = RestoreStrategy(
    find_anchor=find_anchor_insertion_line,
    find_title=find_title_insertion_line,
)
register_restore_strategy(_CURRENT_ARCHIVE_VERSION, _BUILTIN_STRATEGY)
register_restore_strategy("builtin", _BUILTIN_STRATEGY)


def _prepend_directive(content: str, directive_data: dict[str, Any]) -> str:
    """Return ``content`` with a doto directive prepended at the top of the file.

    Used for the TOP_OF_PAGE fallback when the file has no heading to anchor
    under, so the restored directive still lands at the document START rather
    than being appended at the end.

    Args:
        content: Current file content.
        directive_data: Task data for the directive (must include ``id``).

    Returns:
        New content with the directive at the top.
    """
    from doxtr_doto.sync.rst_writer import render_directive_text

    directive_text = render_directive_text(directive_data)
    if not content.strip():
        return directive_text + "\n"
    return f"{directive_text}\n\n{content}"


def _resolve_rst_path(rst_file: str, srcdir: Path) -> Path | None:
    """Resolve a recorded ``rst_file`` to a concrete source path.

    The sync layer records ``rst_file`` either as a real path (``tasks.rst``)
    or as a docname with no extension. This tries the raw path first and then
    the ``.rst`` extension so both forms resolve.

    The resolved path is validated to live inside ``srcdir``: a tampered
    ``original_rst_file`` such as ``../../evil`` escapes the source tree, so
    this returns None for it and the caller refuses to write (treating it like
    a missing page). This prevents a path-traversal write outside ``srcdir``.

    Args:
        rst_file: Recorded RST file path or docname.
        srcdir: Sphinx source directory.

    Returns:
        The best-guess concrete path (which may still not exist), or None when
        the path would escape ``srcdir``.
    """
    for candidate in (rst_file, f"{rst_file}.rst"):
        try:
            resolved = validate_path_within(candidate, srcdir)
        except ValueError:
            # Escapes srcdir: refuse. Keep checking the other candidate form
            # in case only one of them is malicious (both share the same
            # ``..`` though, so this effectively rejects traversal entirely).
            return None
        if resolved.exists():
            return resolved
    # Neither form exists; return the containment-validated raw path so the
    # caller can report PAGE_MISSING against it.
    try:
        return validate_path_within(rst_file, srcdir)
    except ValueError:
        return None


def _resolve_strategy(archive_meta: dict[str, Any]) -> RestoreStrategy:
    """Select the restore strategy for a captured ``_archive`` block.

    The strategy is chosen from :data:`_RESTORE_STRATEGIES` by, in order:

    1. an explicit ``strategy`` name in ``archive_meta`` (string key), then
    2. the ``version`` number of the ``_archive`` block (integer key).

    A missing or unknown version/strategy falls back to the built-in default
    (version 1), so an older or forward-written anchor still restores. See
    :func:`register_restore_strategy` for how a downstream project plugs in an
    alternative without editing core.

    Args:
        archive_meta: The task's ``_sync._archive`` dict.

    Returns:
        The resolved :class:`RestoreStrategy`.
    """
    strategy_name = archive_meta.get("strategy")
    if strategy_name is not None and strategy_name in _RESTORE_STRATEGIES:
        return _RESTORE_STRATEGIES[strategy_name]
    version = archive_meta.get("version", _CURRENT_ARCHIVE_VERSION)
    return _RESTORE_STRATEGIES.get(version, _RESTORE_STRATEGIES[_CURRENT_ARCHIVE_VERSION])


def restore_task_to_rst(task: dict[str, Any], srcdir: Path | str) -> RestoreResult:
    """Restore an archived task's directive to its original place.

    Uses the restore anchor captured at archive time (stored under
    ``task["_sync"]["_archive"]``) to decide between re-inserting at the exact
    original location, falling back to the top of the page, or failing with a
    renamed/deleted-page error. See the module docstring for the full rules.

    The anchor-match / top-of-page detection is delegated to a
    :class:`RestoreStrategy` resolved from the ``_archive`` block's
    ``version``/``strategy`` (see :func:`_resolve_strategy`), so a downstream
    project can register an alternative without editing core.

    This does not clear the task's archived flag or persist the JSON \u2014 callers
    (CLI ``reopen`` / build-time ``reopen_task``) own that. It only performs the
    RST re-insertion and reports which path was taken.

    Args:
        task: The task data dict (including ``id`` and ``_sync``).
        srcdir: Sphinx source directory.

    Returns:
        A :class:`RestoreResult` describing the outcome.
    """
    srcdir = Path(srcdir)
    sync = task.get("_sync", {}) or {}
    archive_meta = sync.get("_archive", {}) or {}

    original_rst_file = archive_meta.get("original_rst_file") or sync.get("rst_file")
    page_title = archive_meta.get("page_title")

    # Build the task data for directive generation (needs an 'id').
    task_id = task.get("id") or task.get("_id")
    directive_data = dict(task)
    if task_id and "id" not in directive_data:
        directive_data["id"] = task_id

    # No original file recorded at all: nothing to anchor to. Treat like a
    # missing page so the caller does not silently relocate.
    if not original_rst_file:
        return RestoreResult(
            success=False,
            path=RestorePath.PAGE_MISSING,
            rst_file=None,
            page_title=page_title,
            message=(
                "this doto has no recorded original page; it cannot be "
                "restored to a specific location"
            ),
        )

    rst_path = _resolve_rst_path(original_rst_file, srcdir)

    # PAGE RENAMED/DELETED (or a tampered traversal path that escapes srcdir,
    # where _resolve_rst_path returned None): fail with a retrace message and
    # never write outside the source tree.
    if rst_path is None or not rst_path.exists():
        title_part = f'"{page_title}"' if page_title else "(unknown title)"
        return RestoreResult(
            success=False,
            path=RestorePath.PAGE_MISSING,
            rst_file=original_rst_file,
            page_title=page_title,
            message=(
                f"this doto was originally on a page with title {title_part} "
                f'at "{original_rst_file}", which no longer exists; '
                f"it was not relocated so you can retrace where it belongs"
            ),
        )

    content = rst_path.read_text(encoding="utf-8")

    strategy = _resolve_strategy(archive_meta)
    preceding = archive_meta.get("preceding_lines") or []
    anchor_line = strategy.find_anchor(content, preceding)

    if anchor_line is not None:
        # ANCHOR: insert right after the matched preceding context.
        new_content = insert_directive_into_content(content, directive_data, after_line=anchor_line)
        _write(rst_path, new_content)
        return RestoreResult(
            success=True,
            path=RestorePath.ANCHOR,
            rst_file=original_rst_file,
            page_title=page_title,
            message=f"restored at original location in {original_rst_file}",
        )

    # TOP_OF_PAGE: heavily modified file. Insert under the first heading. When
    # the file has no heading, find_title returns None; insert at the document
    # START (prepend) rather than letting insert_directive_into_content
    # silently append to the end, so the reported "top of page" stays accurate.
    title_line = strategy.find_title(content)
    if title_line is not None:
        new_content = insert_directive_into_content(content, directive_data, after_line=title_line)
    else:
        new_content = _prepend_directive(content, directive_data)
    _write(rst_path, new_content)
    return RestoreResult(
        success=True,
        path=RestorePath.TOP_OF_PAGE,
        rst_file=original_rst_file,
        page_title=page_title,
        message=(
            f"anchor no longer matched (heavily modified file); "
            f"inserted at top of {original_rst_file}"
        ),
    )


def _write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via the rst_writer helper.

    Args:
        path: Destination file path.
        content: New file content.
    """
    from doxtr_doto.sync.rst_writer import _atomic_write

    _atomic_write(path, content)
