"""RST file modification for bidirectional sync.

This module provides utilities for parsing, modifying, and generating
doto directives in RST files as part of the bidirectional sync process.

Key functions:
- generate_directive_text: Create RST directive text from task data
- insert_doto_directive: Add a new directive to an RST file
- update_doto_directive: Modify an existing directive in place
- remove_doto_directive: Remove a directive from an RST file
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Directive, Parser, directives, roles
from docutils.utils import Reporter, new_document

from doxtr_doto.exceptions import DotoRstWriteError, DotoValidationError

#: docutils reporter level that suppresses all system messages and never
#: halts. docutils severity levels run 0 (DEBUG) .. 4 (SEVERE); setting the
#: report/halt level one above SEVERE silences the "Unknown directive type"
#: messages the registry scoping (see :func:`_parse_rst_for_directives`)
#: deliberately produces, without turning any of them into a parse-aborting
#: error.
_SUPPRESS_ALL_MESSAGES = Reporter.SEVERE_LEVEL + 1

#: Serializes the global docutils directive/role registry swap performed by
#: :func:`_parse_rst_for_directives`. That swap mutates process-global state
#: (``directives._directives`` / ``roles._roles``) for the duration of a
#: parse; the lock prevents a concurrent or reentrant write-back parse from
#: racing the save/restore and permanently clobbering the real registry.
#: Sphinx builds are single-threaded today, so this is defensive insurance;
#: it is a non-reentrant lock, so a parse must never recurse into another.
_PARSE_REGISTRY_LOCK = threading.Lock()

# Matches an indented directive option line like ``   :id:`` and captures the
# leading indentation. Shared by insert_id_into_directive_at_line and
# _update_directive_content so both detect option indentation identically.
_OPTION_LINE_RE = re.compile(r"^(\s+):[\w-]+:")


def _ensure_doto_directive_registered() -> dict[str, type[Directive]]:
    """Register env-free doto directive stubs with docutils for parsing.

    Registers safe, metadata-only parser stubs for every doto directive
    that can appear in an RST file (``doto``, ``doto-list``,
    ``doto-summary``). This allows the standalone docutils ``Parser`` used
    by :func:`_parse_rst_for_directives` to parse files without errors.

    Returns:
        A mapping of directive name to its env-free stub class, so the caller
        can scope the global directive registry to just these stubs during a
        standalone parse.

    The standalone parser has no Sphinx ``env`` on its settings object. The
    real ``doto-list`` / ``doto-summary`` directives are
    :class:`~sphinx.util.docutils.SphinxDirective` subclasses whose
    ``run()`` reads ``self.env`` (via ``self.state.document.settings.env``),
    so invoking them during standalone parsing raises
    ``AttributeError: 'Values' object has no attribute 'env'``. These stubs
    replace them with plain docutils ``Directive`` subclasses that never
    touch ``env`` and return nothing, so parsing succeeds. Only the ``doto``
    stub captures metadata; the list/summary stubs exist purely so the
    parser does not fail on them.

    Always registers our parser-specific directives, even if the real
    doto directives were registered by Sphinx during a build or by tests.
    This ensures consistent, env-free behavior for RST parsing operations.
    """

    class DotoParserDirective(Directive):  # type: ignore[misc]  # docutils Directive is untyped (no stubs)
        """Minimal doto directive for parsing purposes.

        This directive is used solely for parsing RST content to extract
        doto directive information. It does not render anything.
        """

        required_arguments = 0
        optional_arguments = 1
        final_argument_whitespace = True
        has_content = True
        option_spec = {
            "id": directives.unchanged,
            "assignee": directives.unchanged,
            "priority": directives.unchanged,
            "status": directives.unchanged,
            "due": directives.unchanged,
            "tags": directives.unchanged,
            "depends-on": directives.unchanged,
            "progress": directives.unchanged,
            "raci": directives.unchanged,
            "created": directives.unchanged,
            "updated": directives.unchanged,
        }

        def run(self) -> list[nodes.Node]:
            """Process the directive and return container node with metadata."""
            node = nodes.container()
            node["classes"].append("doto-directive")
            node["arguments"] = self.arguments
            node["options"] = self.options
            node["content"] = list(self.content)
            node.line = self.lineno
            node["content_offset"] = self.content_offset
            return [node]

    # Import the real directives' option_spec KEYS only (class attributes,
    # no env-dependent code runs at import time) so the stubs' accepted
    # options stay in sync with the real directives as options are added.
    from doxtr_doto.directives.doto_list import DotoListDirective
    from doxtr_doto.directives.doto_summary import DotoSummaryDirective

    class _DotoNoopDirective(Directive):  # type: ignore[misc]  # docutils Directive is untyped (no stubs)
        """Env-free stub for a doto directive that renders nothing.

        Used for ``doto-list`` / ``doto-summary`` during standalone RST
        parsing. Accepts arguments/options/content permissively so docutils
        does not error, and never touches ``self.env``.
        """

        required_arguments = 0
        optional_arguments = 1
        final_argument_whitespace = True
        has_content = True
        option_spec: dict[str, Any] = {}

        def run(self) -> list[nodes.Node]:
            """Return nothing; this stub exists only to parse without error."""
            return []

    class DotoListParserDirective(_DotoNoopDirective):
        option_spec = dict.fromkeys(DotoListDirective.option_spec, directives.unchanged)

    class DotoSummaryParserDirective(_DotoNoopDirective):
        option_spec = dict.fromkeys(DotoSummaryDirective.option_spec, directives.unchanged)

    class DotoArchiveParserDirective(_DotoNoopDirective):
        """Env-free stub for ``doto-archive`` during standalone RST parsing."""

        option_spec: dict[str, Any] = {}

    # Always register our parser directives, overwriting any existing ones.
    # This ensures consistent, env-free behavior regardless of what other
    # code (like Sphinx during a real build) may have registered.
    directives.register_directive("doto", DotoParserDirective)
    directives.register_directive("doto-list", DotoListParserDirective)
    directives.register_directive("doto-summary", DotoSummaryParserDirective)
    directives.register_directive("doto-archive", DotoArchiveParserDirective)

    # Return the stub mapping so the caller can scope the global directive
    # registry to *only* these env-free stubs during a standalone parse (see
    # :func:`_parse_rst_for_directives`). This prevents any *other* directive
    # that Sphinx registered globally during a build (e.g. ``toctree`` and
    # other ``SphinxDirective`` subclasses whose ``run()`` reads ``self.env``)
    # from executing env-dependent code and raising
    # ``AttributeError: 'Values' object has no attribute 'env'``.
    return {
        "doto": DotoParserDirective,
        "doto-list": DotoListParserDirective,
        "doto-summary": DotoSummaryParserDirective,
        "doto-archive": DotoArchiveParserDirective,
    }


def _parse_rst_for_directives(content: str) -> list[dict[str, Any]]:
    """Parse RST content and extract doto directive information.

    The parse is performed with a standalone docutils ``Parser`` that has no
    Sphinx ``env`` on its settings. During a real Sphinx build, Sphinx
    registers its own directives and roles into the *global* docutils
    registries; several of those (e.g. ``toctree`` and other
    ``SphinxDirective`` subclasses) read ``self.env`` in ``run()`` and would
    raise ``AttributeError: 'Values' object has no attribute 'env'`` if they
    executed during this env-free parse, aborting the write-back.

    To stay robust against *any* such globally-registered directive/role (not
    just the doto ones), the global directive and role lookup caches are
    temporarily replaced for the duration of the parse: directives are scoped
    to just our env-free doto stubs, and roles are cleared. Any other
    directive/role in the file then resolves as *unknown*, which docutils
    turns into a harmless ``system_message`` node rather than executing
    env-dependent code. The original registries are restored in a ``finally``
    block so a build's real directives/roles are left intact.

    Args:
        content: RST file content.

    Returns:
        List of directive info dicts with keys:
        - line: 1-indexed line number where directive starts
        - arguments: list of directive arguments (title)
        - options: dict of directive options
        - content: list of content lines
        - content_offset: line number where content starts
    """
    stubs = _ensure_doto_directive_registered()

    parser = Parser()
    settings = get_default_settings(Parser)
    # Suppress docutils reporter output. Scoping the registry (below) makes
    # every non-doto directive/role resolve as "unknown", which docutils
    # reports as an ERROR-level system_message; those are expected and purely
    # cosmetic here, so raise the report level above SEVERE to keep the
    # build log clean during write-back (and never halt the parse on them).
    settings.report_level = _SUPPRESS_ALL_MESSAGES
    settings.halt_level = _SUPPRESS_ALL_MESSAGES
    document = new_document("<rst-doc>", settings=settings)

    # Scope the global docutils registries to our env-free stubs for the
    # duration of the parse, then restore them. ``_directives`` and
    # ``_roles`` are docutils *private* module-level lookup caches (no public
    # API exposes them); replacing them makes every non-doto directive/role
    # resolve as unknown (a harmless system_message) instead of running
    # env-dependent Sphinx code. Keys must be normalized (lower-cased) to
    # match the lookup. The swap mutates process-global state, so it is
    # serialized by ``_PARSE_REGISTRY_LOCK`` and restored in a ``finally``
    # (covering both exceptions and concurrency). A docutils upgrade that
    # renames these internals would raise ``AttributeError`` here, failing
    # loudly rather than silently reintroducing the env-crash.
    with _PARSE_REGISTRY_LOCK:
        saved_directives = directives._directives
        saved_roles = roles._roles
        directives._directives = {name.lower(): cls for name, cls in stubs.items()}
        roles._roles = {}
        try:
            parser.parse(content, document)
        finally:
            directives._directives = saved_directives
            roles._roles = saved_roles

    result = []
    for node in document.findall(nodes.container):
        if "doto-directive" not in node.get("classes", []):
            continue
        result.append(
            {
                "line": node.line,
                "arguments": node.get("arguments", []),
                "options": node.get("options", {}),
                "content": node.get("content", []),
                "content_offset": node.get("content_offset", 0),
            }
        )

    return result


def _scan_directive_end_line(lines: list[str], start_line: int) -> int:
    """Return the end line (1-indexed, exclusive) of an option-only directive.

    Used when a directive has no body content: starting from its header line,
    scan forward and treat indented (or blank) lines as part of the directive,
    stopping at the first non-indented, non-blank line. This is the single
    source of truth for "where does an option-only ``.. doto::`` directive
    end", shared by :func:`_find_directive_boundaries` and
    :func:`_find_last_directive_line` so the two cannot drift.

    Args:
        lines: The file split into lines (no trailing newlines).
        start_line: 1-indexed line of the directive header.

    Returns:
        The 1-indexed line number just past the last line of the directive.
    """
    end_line = start_line
    for i in range(start_line - 1, len(lines)):
        line = lines[i]
        # The directive header line itself is always part of the directive.
        if i == start_line - 1:
            end_line = i + 1
            continue
        # Blank lines within the directive's options are okay.
        if not line.strip():
            continue
        # A non-indented, non-blank line means the directive has ended.
        if not (line.startswith(" ") or line.startswith("\t")):
            break
        # This indented line is part of the directive.
        end_line = i + 1
    return end_line


def _find_directive_boundaries(
    content: str,
    task_id: str,
    rst_line: int | None = None,
) -> tuple[int, int] | None:
    """Find the character boundaries of a doto directive.

    Uses docutils to properly parse the RST and identify directive boundaries,
    handling nested content correctly. A directive is matched first by its
    ``:id:`` option. If no directive carries ``task_id`` and ``rst_line`` is
    given, it falls back to the directive whose header is on that line — this
    locates a *bare* directive (one with no ``:id:`` yet) so an UPDATE for an
    auto-generated id can still find it.

    Args:
        content: Full file content.
        task_id: Task ID to find.
        rst_line: 1-indexed header line to fall back to when no ``:id:``
            matches, or None to disable the fallback.

    Returns:
        Tuple of (start_pos, end_pos) character positions, or None if not found.
    """
    directives_info = _parse_rst_for_directives(content)

    # Build line start positions for character offset calculation
    lines = content.split("\n")
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line) + 1)  # +1 for newline

    # Match by :id: first; fall back to the directive on ``rst_line`` only when
    # nothing matched by id (so an explicit id always wins over a line guess).
    matched = None
    for info in directives_info:
        if info["options"].get("id") == task_id:
            matched = info
            break
    if matched is None and rst_line is not None:
        for info in directives_info:
            if info["line"] == rst_line:
                matched = info
                break
    if matched is None:
        return None

    info = matched
    # Found the directive
    start_line = info["line"]  # 1-indexed
    start_pos = line_starts[start_line - 1]

    # Determine end position
    content_lines = info["content"]
    content_offset = info["content_offset"]

    if content_lines:
        # Directive has content - ends after last content line
        end_line = content_offset + len(content_lines)
    else:
        # No content - scan forward to where the option block ends.
        end_line = _scan_directive_end_line(lines, start_line)

    # Get character position for end
    end_pos = line_starts[end_line] if end_line < len(line_starts) else len(content)

    return start_pos, end_pos


def _cleanup_stale_tmp_files(path: Path) -> None:
    """Remove stale .tmp files in the same directory.

    Args:
        path: Path to the main file (used to find directory).
    """
    if not path.parent.exists():
        return
    # Find all .tmp files matching our pattern
    for tmp_file in path.parent.glob("*.tmp"):
        try:
            tmp_file.unlink()
        except OSError:
            pass  # Ignore errors removing stale files


#: Matches a paragraph break in a directive title: a blank line (optionally
#: containing only whitespace) separating two blocks of text. Used by
#: :func:`_split_title_and_body_paragraphs` to tell a hard-wrapped single
#: paragraph apart from a genuine multi-paragraph title.
_PARAGRAPH_BREAK_RE = re.compile(r"\n[^\S\n]*\n")


def _split_title_and_body_paragraphs(title: str) -> tuple[str, list[str]]:
    """Split a directive title into a one-line title and extra body paragraphs.

    The ``.. doto::`` argument must be a single "endless" line: reST does not
    need to honour manual line breaks in the title (the editor/view component
    wraps long lines), so any single newlines inside a paragraph are collapsed
    to single spaces. A title that contains a blank-line paragraph break is
    genuinely multi-paragraph; only the FIRST paragraph can live on the
    directive argument line, so the remaining paragraphs are returned for
    relocation into the directive body (where multi-line content is valid
    reST).

    Args:
        title: The raw title text (may contain newlines / blank-line breaks).

    Returns:
        A ``(one_line_title, extra_body_paragraphs)`` tuple. ``one_line_title``
        is the first paragraph with its internal single newlines collapsed to
        spaces. ``extra_body_paragraphs`` is the list of remaining paragraphs
        (each also collapsed to a single line), empty when the title is a
        single paragraph.
    """
    paragraphs = _PARAGRAPH_BREAK_RE.split(title)

    def _collapse(paragraph: str) -> str:
        # Collapse single newlines (and surrounding whitespace) within a
        # paragraph to single spaces so each paragraph is one endless line.
        return " ".join(paragraph.split())

    one_line_title = _collapse(paragraphs[0])
    extra = [_collapse(p) for p in paragraphs[1:] if p.strip()]
    return one_line_title, extra


def generate_directive_text(task_data: dict[str, Any]) -> str:
    """Generate RST directive text from task data.

    Creates a properly formatted `.. doto::` directive with all
    task metadata as options.

    Args:
        task_data: Dictionary containing task fields.

    Returns:
        RST directive text string.

    Raises:
        ValueError: If 'id' is missing from task_data.
    """
    task_id = task_data.get("id")
    if not task_id:
        raise ValueError(
            "generate_directive_text requires 'id' in task_data. "
            "Pass task_data with the key injected: data['id'] = task_id"
        )

    lines = []

    # Directive header with title, emitted as a SINGLE endless line. reST does
    # not need to honour manual line breaks in the title (the editor/view
    # component wraps long lines), so single newlines within the title's first
    # paragraph are collapsed to spaces and written on one line. Emitting the
    # raw title newline verbatim corrupted the directive: docutils kept only
    # line 1 as the argument and reinterpreted the unindented remainder as
    # body, orphaning the ``:id:``/option block, which made the task look
    # missing and cascaded into duplicate re-insertions every build. A
    # genuinely multi-paragraph title (two or more blocks separated by a blank
    # line) cannot live on the argument line, so its trailing paragraphs are
    # relocated into the directive body below, where multi-line content is
    # valid reST.
    title = task_data.get("title", "")
    one_line_title, title_body_paragraphs = _split_title_and_body_paragraphs(title)
    lines.append(f".. doto:: {one_line_title}")

    # Required option: id
    lines.append(f"   :id: {task_id}")

    # Optional fields - only include if set
    if task_data.get("assignee"):
        lines.append(f"   :assignee: {task_data['assignee']}")

    if task_data.get("priority") and task_data["priority"] != "medium":
        lines.append(f"   :priority: {task_data['priority']}")

    if task_data.get("status") and task_data["status"] != "open":
        lines.append(f"   :status: {task_data['status']}")

    if task_data.get("due"):
        lines.append(f"   :due: {task_data['due']}")

    if task_data.get("tags"):
        tags = task_data["tags"]
        if isinstance(tags, list):
            tags = ", ".join(tags)
        lines.append(f"   :tags: {tags}")

    if task_data.get("depends_on"):
        deps = task_data["depends_on"]
        if isinstance(deps, list):
            deps = ", ".join(deps)
        lines.append(f"   :depends-on: {deps}")

    if task_data.get("progress") is not None:
        lines.append(f"   :progress: {task_data['progress']}")

    if task_data.get("raci"):
        from doxtr_doto.raci import format_raci

        raci_str = format_raci(task_data["raci"])
        if raci_str:
            lines.append(f"   :raci: {raci_str}")

    # Merge any relocated title paragraphs in front of the existing body,
    # separated by a blank line so nothing is lost. Each entry here is a
    # single endless-line paragraph; blank entries between them preserve
    # paragraph separation when the body is re-indented below.
    body_paragraphs: list[str] = list(title_body_paragraphs)
    existing_body = task_data.get("body")
    if existing_body:
        body_paragraphs.append(existing_body)

    # Body content
    if body_paragraphs:
        lines.append("")  # Blank line before body
        # Join paragraphs with a blank-line separator so paragraph breaks
        # survive the re-indent round-trip (blank lines emitted as empty
        # strings, every other line indented 3 spaces).
        body = "\n\n".join(body_paragraphs)
        for body_line in body.split("\n"):
            lines.append(f"   {body_line}" if body_line else "")

    return "\n".join(lines)


# =============================================================================
# Overridable directive-rendering seam (modularity)
# =============================================================================
#
# :func:`generate_directive_text` is the DEFAULT directive renderer. All
# directive knowledge lives in one place, and internal callers route through
# :func:`render_directive_text` (the single indirection point) rather than
# calling the default directly, so a child theme or downstream project can swap
# ALL directive-text rendering without editing core (mirrors
# :func:`doxtr_doto.xlink._get_resolver_fn` and the restore-strategy registry in
# :mod:`doxtr_doto.sync.restore`).

#: Signature of a directive renderer: ``(task_data) -> rst text``.
DirectiveRenderer = Callable[[dict[str, Any]], str]

#: THE single indirection point for directive rendering. Internal callers
#: dispatch through :func:`render_directive_text`, which reads this attribute,
#: so reassigning it (via :func:`register_directive_renderer`) swaps rendering
#: everywhere. Defaults to :func:`generate_directive_text`.
_directive_renderer: DirectiveRenderer = generate_directive_text


def render_directive_text(task_data: dict[str, Any]) -> str:
    """Render RST directive text for ``task_data`` via the active renderer.

    The single dispatch point for directive rendering (modularity seam):
    internal callers use this instead of :func:`generate_directive_text`
    directly so a downstream/child theme can call
    :func:`register_directive_renderer` to replace ALL directive rendering with
    its own implementation without editing core. Defaults to
    :func:`generate_directive_text`.

    Args:
        task_data: Dictionary containing task fields (must include ``id``).

    Returns:
        RST directive text string.
    """
    return _directive_renderer(task_data)


def register_directive_renderer(fn: DirectiveRenderer) -> None:
    """Swap the active directive renderer used by :func:`render_directive_text`.

    Downstream extension point: a child theme can register its own
    ``(task_data) -> rst text`` renderer and have every internal directive
    insertion/restore use it, without editing core. Call
    :func:`reset_directive_renderer` to restore the built-in default.

    Args:
        fn: The replacement renderer callable.
    """
    global _directive_renderer
    _directive_renderer = fn


def reset_directive_renderer() -> None:
    """Reset the directive renderer to the built-in :func:`generate_directive_text`."""
    global _directive_renderer
    _directive_renderer = generate_directive_text


def insert_id_into_directive_at_line(
    content: str,
    lineno: int,
    task_id: str,
) -> str:
    """Insert an ``:id:`` option into a bare doto directive at a line.

    Locates the ``.. doto::`` directive starting at (or the nearest at/after)
    the given 1-indexed line among parsed directives that currently have NO
    ``:id:`` option, and injects a ``:id: <task_id>`` option line immediately
    after the directive header line (before any other options or body).

    This is used by the sync write-back path to make auto-generated
    ``{docname}-L{lineno}`` IDs stable: once the ID is written into the RST
    directive, subsequent builds see the explicit ``:id:`` and reuse it
    instead of generating a new line-based ID.

    A directive that already has an ``:id:`` option is never matched, so
    directives with explicit IDs are left untouched.

    Args:
        content: Full RST file content.
        lineno: 1-indexed line number where the bare directive starts.
        task_id: The task ID to inject into the directive.

    Returns:
        Modified content string. Returned unchanged if no matching bare
        directive is found at/after the given line.
    """
    if not content or not task_id:
        return content

    directives_info = _parse_rst_for_directives(content)

    # Consider only directives that currently have no :id: option, since a
    # bare auto-generated directive has none. Choose the one whose starting
    # line is nearest at/after the recorded lineno so multiple bare
    # directives in one file each get their own correct id.
    candidate: dict[str, Any] | None = None
    for info in directives_info:
        if info["options"].get("id"):
            continue
        info_line = info.get("line")
        if info_line is None or info_line < lineno:
            continue
        if candidate is None or info_line < candidate["line"]:
            candidate = info

    if candidate is None:
        return content

    lines = content.split("\n")
    header_index = candidate["line"] - 1  # 0-indexed header line
    if header_index < 0 or header_index >= len(lines):
        return content

    header_line = lines[header_index]
    # Match the directive's own option indentation. Options are indented
    # relative to the directive header; default to header indent + 3 spaces.
    header_indent = len(header_line) - len(header_line.lstrip(" "))
    option_indent = " " * (header_indent + 3)

    # Prefer an existing option line's indentation when present so we match
    # the directive's established style exactly.
    for i in range(header_index + 1, len(lines)):
        existing = lines[i]
        option_match = _OPTION_LINE_RE.match(existing)
        if option_match:
            option_indent = option_match.group(1)
            break
        if existing.strip() and not (existing.startswith(" ") or existing.startswith("\t")):
            break

    id_line = f"{option_indent}:id: {task_id}"
    lines.insert(header_index + 1, id_line)
    return "\n".join(lines)


def remove_doto_directive(rst_file: Path | str, task_id: str) -> bool:
    """Remove a doto directive from an RST file.

    Uses docutils to properly parse the RST and identify directive boundaries,
    handling nested content correctly. Surgically removes the directive
    matching the given task ID, preserving all other content.

    Args:
        rst_file: Path to the RST file.
        task_id: The task ID to remove.

    Returns:
        True if removed, False if not found.

    Raises:
        DotoValidationError: If task_id is empty.
        DotoRstWriteError: If file cannot be read or written.
    """
    if not task_id:
        raise DotoValidationError("task_id cannot be empty")

    rst_file = Path(rst_file)
    if not rst_file.exists():
        return False

    try:
        content = rst_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise DotoRstWriteError(
            str(rst_file),
            task_id,
            f"Failed to read {rst_file}: {e}",
        ) from e

    # Delegate to content-level function
    new_content = remove_directive_from_content(content, task_id)
    if new_content == content:
        return False

    try:
        _atomic_write(rst_file, new_content)
    except Exception as e:
        raise DotoRstWriteError(
            str(rst_file),
            task_id,
            f"Failed to write {rst_file}: {e}",
        ) from e

    return True


#: Number of preceding non-blank source lines captured as the positional
#: restore anchor when a directive is removed. More lines make the anchor more
#: specific (less likely to match the wrong place) at the cost of being more
#: fragile to edits; three balances both for typical task pages.
_ANCHOR_PRECEDING_LINES = 3


def _find_first_heading(content: str) -> tuple[int, str] | None:
    """Return the first section heading in RST ``content``, or None.

    A section heading is a line of text immediately followed by a run of
    section-underline punctuation (``=``, ``-``, ``~``, etc.) at least as long
    as the title text. An optional matching overline directly above the title
    is tolerated (the loop skips the overline and resolves to the real title).

    This is the single source of truth for "where is the first heading",
    shared by :func:`extract_page_title` (which wants the title text) and
    :func:`find_title_insertion_line` (which wants the underline line number).

    Args:
        content: Full RST file content.

    Returns:
        A ``(underline_line, title_text)`` tuple where ``underline_line`` is the
        1-indexed line number of the section underline, or None if the file has
        no section heading.
    """
    section_chars = set("=-~`:'\"^_*+#<>.")
    lines = content.split("\n")
    for i, line in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        # Candidate underline on the next line.
        if i + 1 < len(lines):
            underline = lines[i + 1].strip()
            if (
                underline
                and set(underline) <= section_chars
                and len(set(underline)) == 1
                and len(underline) >= len(text)
            ):
                # Skip an overline (same punctuation above the title text):
                # an overline is itself an all-punctuation line, so it is not
                # a valid title. The loop reaches the real title text next.
                if set(text) <= section_chars and len(set(text)) == 1:
                    continue
                # Underline is at i+1 (0-indexed) => i+2 (1-indexed).
                return i + 2, text
    return None


def extract_page_title(content: str) -> str | None:
    """Return the document title (first section heading) of RST ``content``.

    The title is the text of the first section heading (see
    :func:`_find_first_heading`). Returns None when no heading is found.

    Used to record which page an archived task came from so a renamed/deleted
    page can be reported to the user by its human-readable title.

    Args:
        content: Full RST file content.

    Returns:
        The page title text, or None if the file has no section heading.
    """
    heading = _find_first_heading(content)
    return heading[1] if heading is not None else None


def capture_restore_anchor(content: str, task_id: str) -> dict[str, Any] | None:
    """Capture a positional anchor for a doto directive before it is removed.

    Extracts enough context to later re-insert the directive at the SAME place
    in the file (see :func:`doxtr_doto.sync.restore.restore_task_to_rst`). The
    directive text itself is NOT stored: restore regenerates the directive from
    the task's current fields via ``generate_directive_text`` (so the restored
    directive reflects the reopen status, not the archived one). The returned
    anchor records:

    * ``version`` -- the ``_archive`` schema version (currently 1), so the
      restore layer can branch defensively as the capture format evolves.
    * ``page_title`` -- the document title / first section heading of the file,
      used in the renamed/deleted error message so the user can retrace a
      relocated task.
    * ``preceding_lines`` -- the up-to :data:`_ANCHOR_PRECEDING_LINES` non-blank
      source lines immediately before the directive header. This is the
      positional anchor: restore re-inserts the directive right after the last
      of these lines when they are still present and unambiguous.
    * ``directive_line`` -- the 1-indexed header line the directive was on, kept
      for diagnostics.

    Args:
        content: Full RST file content (before removal).
        task_id: The task ID whose directive is being removed.

    Returns:
        An anchor dict, or None if the directive could not be located.
    """
    boundaries = _find_directive_boundaries(content, task_id)
    if boundaries is None:
        return None

    start_pos, _end_pos = boundaries

    # Determine the header line (1-indexed) from the start character offset.
    header_line = content.count("\n", 0, start_pos) + 1
    lines = content.split("\n")

    # Collect up to _ANCHOR_PRECEDING_LINES non-blank lines immediately above
    # the directive header, nearest-last (so the final element is the line
    # directly above the directive).
    preceding: list[str] = []
    i = header_line - 2  # 0-indexed line just above the header
    while i >= 0 and len(preceding) < _ANCHOR_PRECEDING_LINES:
        candidate = lines[i]
        if candidate.strip():
            preceding.insert(0, candidate.rstrip())
        i -= 1

    return {
        "version": 1,
        "page_title": extract_page_title(content),
        "preceding_lines": preceding,
        "directive_line": header_line,
    }


def _find_last_directive_line(content: str) -> int | None:
    """Return the line number of the last line of the last doto directive, or None.

    Args:
        content: RST file content.

    Returns:
        1-indexed line number of the last line of the last directive, or None if no directives.
    """
    directives_info = _parse_rst_for_directives(content)
    if not directives_info:
        return None

    last = directives_info[-1]
    content_lines = last.get("content", [])

    if content_lines:
        # Directive has body content - ends after last content line
        return int(last["content_offset"]) + len(content_lines)

    # No body — scan forward to where the option block ends.
    lines = content.split("\n")
    return _scan_directive_end_line(lines, last["line"])


def insert_doto_directive(
    rst_file: Path | str,
    task_data: dict[str, Any],
    after_line: int | None = None,
) -> bool:
    """Insert a new doto directive into an RST file.

    If after_line is specified, inserts after that line.
    If after_line is None but the file has existing doto directives,
    inserts after the last one. Otherwise, appends to the end of the file.

    Args:
        rst_file: Path to the RST file.
        task_data: Task data dictionary (must contain 'id' key).
        after_line: Line number to insert after (1-indexed), or None for auto.

    Returns:
        True if inserted successfully.

    Raises:
        DotoValidationError: If task_data has no 'id' key.
        DotoRstWriteError: If file cannot be read or written.
    """
    rst_file = Path(rst_file)

    # Guard: task_data must contain 'id'
    task_id = task_data.get("id")
    if not task_id:
        raise DotoValidationError(
            f"insert_doto_directive: task_data must contain 'id'. Got: {list(task_data.keys())}"
        )

    if not rst_file.exists():
        # Create file with just the directive
        try:
            directive_text = render_directive_text(task_data)
            rst_file.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(rst_file, directive_text + "\n")
        except Exception as e:
            raise DotoRstWriteError(
                str(rst_file),
                str(task_id),
                f"Failed to create {rst_file}: {e}",
            ) from e
        return True

    try:
        content = rst_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise DotoRstWriteError(
            str(rst_file),
            str(task_id),
            f"Failed to read {rst_file}: {e}",
        ) from e

    # Delegate to content-level function
    try:
        new_content = insert_directive_into_content(content, task_data, after_line)
    except Exception as e:
        raise DotoRstWriteError(
            str(rst_file),
            str(task_id),
            f"Failed to generate directive: {e}",
        ) from e

    try:
        _atomic_write(rst_file, new_content)
    except Exception as e:
        raise DotoRstWriteError(
            str(rst_file),
            str(task_id),
            f"Failed to write {rst_file}: {e}",
        ) from e

    return True


def update_doto_directive(
    rst_file: Path | str,
    task_id: str,
    updates: dict[str, Any],
) -> bool:
    """Update a doto directive in place.

    Modifies specific fields in an existing directive without
    rewriting the entire directive.

    Args:
        rst_file: Path to the RST file.
        task_id: The task ID to update.
        updates: Dictionary of fields to update.

    Returns:
        True if updated, False if task not found.

    Raises:
        DotoValidationError: If task_id is empty.
        DotoRstWriteError: If file cannot be read or written.
    """
    if not task_id:
        raise DotoValidationError("task_id cannot be empty")

    rst_file = Path(rst_file)
    if not rst_file.exists():
        return False

    try:
        content = rst_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise DotoRstWriteError(
            str(rst_file),
            task_id,
            f"Failed to read {rst_file}: {e}",
        ) from e

    # Delegate to content-level function
    try:
        new_content = update_directive_in_content(content, task_id, updates)
    except Exception as e:
        raise DotoRstWriteError(
            str(rst_file),
            task_id,
            f"Failed to update directive {task_id}: {e}",
        ) from e

    if new_content == content:
        return False

    try:
        _atomic_write(rst_file, new_content)
    except Exception as e:
        raise DotoRstWriteError(
            str(rst_file),
            task_id,
            f"Failed to write {rst_file}: {e}",
        ) from e

    return True


def _find_directive_block(
    content: str, task_id: str, rst_line: int | None = None
) -> tuple[int, int, str] | None:
    """Find a doto directive block by task ID (or line-number fallback).

    Uses docutils to properly parse the RST and identify directive boundaries,
    handling nested content correctly. Matches by ``:id:`` first, falling back
    to ``rst_line`` when no directive carries ``task_id`` (see
    :func:`_find_directive_boundaries`).

    Args:
        content: Full file content.
        task_id: Task ID to find.
        rst_line: 1-indexed header line to fall back to, or None.

    Returns:
        Tuple of (start_pos, end_pos, directive_content) or None if not found.

    Raises:
        DotoValidationError: If task_id is empty.
    """
    if not content:
        return None

    if not task_id:
        raise DotoValidationError("task_id cannot be empty")

    boundaries = _find_directive_boundaries(content, task_id, rst_line)
    if boundaries is None:
        return None

    start_pos, end_pos = boundaries

    # Validate boundaries
    if start_pos < 0 or end_pos > len(content) or start_pos >= end_pos:
        return None

    return start_pos, end_pos, content[start_pos:end_pos]


def _update_directive_content(directive_content: str, updates: dict[str, Any]) -> str:
    """Update fields within a directive's content.

    Handles the three structurally-distinct parts of a ``.. doto::`` directive
    correctly:

    * ``title`` is the directive *argument* on the ``.. doto::`` line, not an
      option, so a title change rewrites that line (it is never emitted as a
      ``:title:`` option).
    * ``body`` is the indented content block after the options, not an option,
      so a body change rewrites the content block (never a ``:body:`` option)
      via :func:`_replace_directive_body`.
    * every other field is a directive *option* (``:name: value``): an
      existing option line is updated in place, and a genuinely new option is
      inserted immediately after the last existing option (before the blank
      line / body), never into the body.

    ``id`` is normally omitted (it is managed by the INSERT_ID path and must
    already be present on the directive). It is only honored here when passed
    explicitly to repair a *bare* directive located by line number, in which
    case it is inserted as the first option (right after the ``.. doto::``
    line). Empty option values are skipped when inserting a new option but
    still applied when updating an existing one (so a field can be cleared).

    Args:
        directive_content: The current directive text.
        updates: Fields to update.

    Returns:
        Updated directive text.
    """
    from doxtr_doto.fields import FIELD_NAME_TO_RST

    lines = directive_content.split("\n")

    # ``title`` and ``body`` are not options. ``id`` is an option but, when
    # present, must be inserted first (right after the marker); it is only
    # supplied here to repair a bare directive. Everything else is a normal
    # option that may be updated or inserted.
    inject_id = updates.get("id") if "id" in updates else None
    option_updates = {
        field: value
        for field, value in updates.items()
        if field not in ("title", "body", "id") and not field.startswith("_")
    }

    result: list[str] = []
    updated_fields: set[str] = set()
    field_map = FIELD_NAME_TO_RST

    # First line is the directive marker: ``.. doto:: <title>``. Rewrite the
    # argument when the title changed, leaving options/body untouched.
    if lines and "title" in updates:
        marker = re.match(r"^(\s*\.\.\s+doto::)(.*)$", lines[0])
        if marker is not None:
            new_title = updates["title"]
            if new_title:
                lines[0] = f"{marker.group(1)} {new_title}"
            else:
                lines[0] = marker.group(1)

    # Repair a bare directive: inject ``:id:`` as the first option, right
    # after the ``.. doto::`` marker line, using the directive's existing
    # option indentation (default 3 spaces).
    if inject_id and lines:
        id_indent = "   "
        for line in lines[1:]:
            option_match = _OPTION_LINE_RE.match(line)
            if option_match:
                id_indent = option_match.group(1)
                break
        lines.insert(1, f"{id_indent}:id: {inject_id}")

    # Update existing option lines in place.
    for line in lines:
        updated = False
        for field, value in option_updates.items():
            rst_field = field_map.get(field, field)
            pattern = rf"^(\s+):{rst_field}:\s*.*$"
            match = re.match(pattern, line)
            if match:
                indent = match.group(1)
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                result.append(f"{indent}:{rst_field}: {value}")
                updated_fields.add(field)
                updated = True
                break
        if not updated:
            result.append(line)

    # Determine the option indentation from an existing option line.
    option_indent = "   "  # Default (3 spaces for RST)
    for line in result:
        option_match = _OPTION_LINE_RE.match(line)
        if option_match:
            option_indent = option_match.group(1)
            break

    # Insert any genuinely-new options immediately AFTER the last existing
    # option line. This keeps new options inside the option block (above the
    # blank line separating options from body) rather than leaking into the
    # body, which previously corrupted the directive.
    insert_pos = 1 if result else 0  # just after the ``.. doto::`` line
    for i, line in enumerate(result):
        if _OPTION_LINE_RE.match(line):
            insert_pos = i + 1

    for field, value in option_updates.items():
        if field in updated_fields:
            continue
        rst_field = field_map.get(field, field)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        if value:  # Only add a new option when it has a value
            result.insert(insert_pos, f"{option_indent}:{rst_field}: {value}")
            insert_pos += 1

    # Rewrite the body (indented content block) when it changed. The body is
    # everything after the first blank line that follows the options; options
    # are never blank-line-separated from the ``.. doto::`` line, so the first
    # blank line reliably marks the options/body boundary.
    if "body" in updates:
        result = _replace_directive_body(result, updates["body"], option_indent)

    return "\n".join(result)


def _replace_directive_body(
    lines: list[str],
    new_body: Any,
    option_indent: str,
) -> list[str]:
    """Return ``lines`` with the directive's body replaced by ``new_body``.

    The body is the indented content block that follows the blank line after
    the directive's options. Any existing body (and the separating blank line)
    is removed and replaced with ``new_body`` re-indented to ``option_indent``.
    An empty ``new_body`` removes the body entirely, leaving just the
    ``.. doto::`` line and its options.

    The directive block's structural trailing newline (which separates it from
    whatever follows, e.g. the next directive) is preserved: a block passed in
    ending with ``\n`` still ends with ``\n`` afterwards. Without this, an
    empty-body update on the last directive before another one would strip the
    terminator and run the two directives together.

    Args:
        lines: The current directive lines (marker + options + optional body).
        new_body: The new body text (may contain newlines), or empty to clear.
        option_indent: The indentation used by the directive's options.

    Returns:
        The directive lines with the body block replaced.
    """
    # Preserve a structural trailing newline: splitting a block that ends with
    # ``\n`` yields a trailing empty element that is the terminator, not a
    # blank body line. Peel it off and restore it at the end.
    has_terminator = len(lines) > 1 and lines[-1] == ""
    work = lines[:-1] if has_terminator else list(lines)

    # Find the first blank line that separates options from body.
    boundary = None
    for i, line in enumerate(work):
        if i == 0:
            continue  # never treat the ``.. doto::`` line as the boundary
        if line.strip() == "":
            boundary = i
            break

    # Head = marker + options (everything up to, excluding, the blank line).
    head = work[: boundary if boundary is not None else len(work)]
    # Drop trailing blank lines from the head so we control spacing precisely.
    while head and head[-1].strip() == "":
        head.pop()

    body_text = "" if new_body is None else str(new_body)
    if not body_text.strip():
        # No body: just the marker + options (plus any structural terminator).
        return [*head, ""] if has_terminator else head

    body_lines = [f"{option_indent}{line}" if line else "" for line in body_text.split("\n")]
    result = [*head, "", *body_lines]
    return [*result, ""] if has_terminator else result


def _atomic_write(path: Path, content: str) -> None:
    """Write content to file atomically with backup.

    Cleans up stale .tmp files before writing.

    Args:
        path: File path.
        content: Content to write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Cleanup stale .tmp files before writing
    _cleanup_stale_tmp_files(path)

    # Write to temp file first
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


# =============================================================================
# Content-level functions for batched updates
# =============================================================================


def update_directive_in_content(
    content: str,
    task_id: str,
    updates: dict[str, Any],
    rst_line: int | None = None,
) -> str:
    """Apply an in-place directive update to RST content string.

    Returns modified content. Does not read or write any file.

    The directive is located by its ``:id:`` option. When no directive carries
    ``task_id`` and ``rst_line`` is given, it falls back to the directive on
    that line — this handles a *bare* directive (no ``:id:`` yet) whose task
    was assigned an auto-generated id. In that case the ``:id:`` is injected
    into the directive as part of the update so the id becomes stable and
    future updates can match it directly.

    Args:
        content: Full RST file content.
        task_id: The task ID to update.
        updates: Fields to update.
        rst_line: 1-indexed header line to fall back to when no ``:id:``
            matches, or None.

    Returns:
        Updated content string (unchanged if task not found).
    """
    directive_match = _find_directive_block(content, task_id, rst_line)
    if directive_match is None:
        return content

    start, end, directive_content = directive_match

    # Decide whether to inject the :id: option. The caller passes the full
    # merged task dict, which ALWAYS carries ``id``; but ``id`` must only be
    # written when repairing a *bare* directive located by the line-number
    # fallback. If any directive already carries ``task_id`` (authoritative
    # whole-file parse, immune to a wrong block slice), the id is already
    # present and must be dropped from the update so it is never duplicated.
    effective_updates = dict(updates)
    effective_updates.pop("id", None)
    if not _file_has_task_id(content, task_id) and not _directive_has_id(directive_content):
        effective_updates["id"] = task_id

    updated = _update_directive_content(directive_content, effective_updates)
    return content[:start] + updated + content[end:]


def _file_has_task_id(content: str, task_id: str) -> bool:
    """Return True if any doto directive in ``content`` has ``:id: task_id``.

    Uses the authoritative docutils parse (via :func:`_parse_rst_for_directives`)
    rather than a slice-local regex, so the "already has this id" decision in
    :func:`update_directive_in_content` cannot be fooled by a wrong block
    boundary.

    Args:
        content: Full RST file content.
        task_id: The task id to look for.

    Returns:
        True when a directive already carries ``task_id`` as its ``:id:``.
    """
    return any(info["options"].get("id") == task_id for info in _parse_rst_for_directives(content))


def _directive_has_id(directive_content: str) -> bool:
    """Return True if the directive block already has an ``:id:`` option.

    Args:
        directive_content: The directive's text block.

    Returns:
        True when an ``:id:`` option line is present.
    """
    return bool(re.search(r"^\s+:id:\s*\S", directive_content, re.MULTILINE))


def remove_directive_from_content(
    content: str,
    task_id: str,
) -> str:
    """Remove a doto directive from RST content string.

    Returns modified content. Does not read or write any file.

    Args:
        content: Full RST file content.
        task_id: The task ID to remove.

    Returns:
        Updated content string (unchanged if task not found).
    """
    boundaries = _find_directive_boundaries(content, task_id)
    if boundaries is None:
        return content

    start_pos, end_pos = boundaries
    new_content = content[:start_pos] + content[end_pos:]
    # Clean up multiple consecutive blank lines
    return re.sub(r"\n{3,}", "\n\n", new_content)


def insert_directive_into_content(
    content: str,
    task_data: dict[str, Any],
    after_line: int | None = None,
) -> str:
    """Insert a new doto directive into RST content string.

    Returns modified content. Does not read or write any file.

    Args:
        content: Full RST file content.
        task_data: Task data dictionary (must contain 'id' key).
        after_line: Line number to insert after (1-indexed), or None for auto.

    Returns:
        Updated content string with new directive inserted.

    Raises:
        ValueError: If 'id' is missing from task_data.
    """
    directive_text = render_directive_text(task_data)
    lines = content.split("\n") if content else []

    # Auto-detect insertion point if not specified
    if after_line is None:
        after_line = _find_last_directive_line(content) if content else None

    if after_line is not None and 0 < after_line <= len(lines):
        # Insert after specified line
        lines.insert(after_line, "")  # Blank line before
        lines.insert(after_line + 1, directive_text)
        lines.insert(after_line + 2, "")  # Blank line after
    else:
        # Append to end
        if lines and lines[-1].strip():
            lines.append("")  # Ensure blank line before
        lines.append(directive_text)
        lines.append("")  # Trailing newline

    return "\n".join(lines)


# =============================================================================
# Restore-to-place helpers (used by doxtr_doto.sync.restore)
# =============================================================================


def find_anchor_insertion_line(
    content: str,
    preceding_lines: list[str],
) -> int | None:
    """Find the 1-indexed line after which an anchored directive should go.

    The anchor is the sequence of ``preceding_lines`` (the non-blank lines that
    sat directly above the directive when it was removed). This looks for that
    exact consecutive run of non-blank lines in ``content`` and returns the
    line number of the LAST line of the run, so the directive can be
    re-inserted immediately after it.

    The match must be unambiguous: if the preceding sequence does not appear,
    or appears more than once, None is returned so the caller falls back to the
    top-of-page strategy ("heavily modified file" rule).

    Blank lines in ``content`` are ignored when matching so trailing/leading
    blank-line churn around the anchor does not defeat the match; the compared
    sequence is the run of non-blank source lines (stripped of trailing
    whitespace, matching how :func:`capture_restore_anchor` stored them).

    Args:
        content: Current RST file content.
        preceding_lines: The anchor's preceding non-blank lines, in order.

    Returns:
        1-indexed line number to insert after, or None when the anchor is
        missing or ambiguous.
    """
    if not preceding_lines:
        return None

    lines = content.split("\n")
    # Build the list of (0-indexed line number, stripped text) for non-blank
    # lines so we can match the anchor against the non-blank sequence while
    # still returning a real line number in the original file.
    nonblank: list[tuple[int, str]] = [
        (idx, line.rstrip()) for idx, line in enumerate(lines) if line.strip()
    ]
    target = [p.rstrip() for p in preceding_lines]
    n = len(target)

    matches: list[int] = []
    for start in range(len(nonblank) - n + 1):
        window = [text for _idx, text in nonblank[start : start + n]]
        if window == target:
            # Record the ORIGINAL 0-indexed line of the last anchor line.
            matches.append(nonblank[start + n - 1][0])

    if len(matches) != 1:
        # Missing (0 matches) or ambiguous (>1) => heavily modified.
        return None

    return matches[0] + 1  # convert to 1-indexed "insert after" line


def find_title_insertion_line(content: str) -> int | None:
    """Find the 1-indexed line after which a top-of-page insertion should go.

    Returns the line number of the section-underline of the file's first
    heading (see :func:`_find_first_heading`), so a directive inserted after it
    lands at the TOP of the page (right under the title) ahead of other
    content. Returns None when the file has no heading (caller then
    prepends/creates normally).

    Args:
        content: Current RST file content.

    Returns:
        1-indexed line number to insert after, or None if no heading found.
    """
    heading = _find_first_heading(content)
    return heading[0] if heading is not None else None
