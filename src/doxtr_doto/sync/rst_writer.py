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
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Directive, Parser, directives
from docutils.utils import new_document

from doxtr_doto.exceptions import DotoRstWriteError, DotoValidationError


def _ensure_doto_directive_registered() -> None:
    """Register the doto directive with docutils for parsing purposes.
    
    This allows docutils to parse doto directives without errors.
    The directive captures metadata needed for finding directive boundaries.
    
    Always registers our parser-specific directive, even if a different
    doto directive was registered by Sphinx tests or other code. This
    ensures consistent behavior for RST parsing operations.
    """
    class DotoParserDirective(Directive):
        """Minimal doto directive for parsing purposes.
        
        This directive is used solely for parsing RST content to extract
        doto directive information. It does not render anything.
        """
        required_arguments = 0
        optional_arguments = 1
        final_argument_whitespace = True
        has_content = True
        option_spec = {
            'id': directives.unchanged,
            'assignee': directives.unchanged,
            'priority': directives.unchanged,
            'status': directives.unchanged,
            'due': directives.unchanged,
            'tags': directives.unchanged,
            'depends-on': directives.unchanged,
            'progress': directives.unchanged,
            'created': directives.unchanged,
            'updated': directives.unchanged,
        }

        def run(self) -> list[nodes.Node]:
            """Process the directive and return container node with metadata."""
            node = nodes.container()
            node['classes'].append('doto-directive')
            node['arguments'] = self.arguments
            node['options'] = self.options
            node['content'] = list(self.content)
            node.line = self.lineno
            node['content_offset'] = self.content_offset
            return [node]

    # Always register our parser directive, overwriting any existing one
    # This ensures consistent behavior regardless of what other code
    # (like Sphinx tests) may have registered
    directives.register_directive('doto', DotoParserDirective)


def _parse_rst_for_directives(content: str) -> list[dict[str, Any]]:
    """Parse RST content and extract doto directive information.
    
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
    _ensure_doto_directive_registered()
    
    parser = Parser()
    settings = get_default_settings(Parser)
    document = new_document('<rst-doc>', settings=settings)
    parser.parse(content, document)
    
    result = []
    for node in document.findall(nodes.container):
        if 'doto-directive' not in node.get('classes', []):
            continue
        result.append({
            'line': node.line,
            'arguments': node.get('arguments', []),
            'options': node.get('options', {}),
            'content': node.get('content', []),
            'content_offset': node.get('content_offset', 0),
        })
    
    return result


def _find_directive_boundaries(
    content: str,
    task_id: str,
) -> tuple[int, int] | None:
    """Find the character boundaries of a doto directive by task ID.
    
    Uses docutils to properly parse the RST and identify directive boundaries,
    handling nested content correctly.
    
    Args:
        content: Full file content.
        task_id: Task ID to find.
        
    Returns:
        Tuple of (start_pos, end_pos) character positions, or None if not found.
    """
    directives_info = _parse_rst_for_directives(content)
    
    # Build line start positions for character offset calculation
    lines = content.split('\n')
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line) + 1)  # +1 for newline
    
    for info in directives_info:
        if info['options'].get('id') != task_id:
            continue
        
        # Found the directive
        start_line = info['line']  # 1-indexed
        start_pos = line_starts[start_line - 1]
        
        # Determine end position
        content_lines = info['content']
        content_offset = info['content_offset']
        
        if content_lines:
            # Directive has content - ends after last content line
            end_line = content_offset + len(content_lines)
        else:
            # No content - find end by scanning for next non-indented line
            # Start from directive line and find where options end
            end_line = start_line
            for i in range(start_line - 1, len(lines)):
                line = lines[i]
                # Skip the directive line itself
                if i == start_line - 1:
                    end_line = i + 1
                    continue
                # Blank lines within directive are okay
                if not line.strip():
                    continue
                # Non-indented non-blank line means directive ended
                if not line.startswith(' ') and not line.startswith('\t'):
                    break
                # This indented line is part of the directive
                end_line = i + 1
        
        # Get character position for end
        end_pos = line_starts[end_line] if end_line < len(line_starts) else len(content)
        
        return start_pos, end_pos
    
    return None


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
    
    # Directive header with title
    title = task_data.get("title", "")
    lines.append(f".. doto:: {title}")
    
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
    
    # Body content
    if task_data.get("body"):
        lines.append("")  # Blank line before body
        body = task_data["body"]
        # Indent body content
        for body_line in body.split("\n"):
            lines.append(f"   {body_line}" if body_line else "")
    
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
        return last["content_offset"] + len(content_lines)
    
    # No body — find end of options by scanning
    lines = content.split("\n")
    end_line = last["line"]
    
    for i in range(last["line"] - 1, len(lines)):
        line = lines[i]
        # Skip the directive line itself
        if i == last["line"] - 1:
            end_line = i + 1
            continue
        # Blank lines within directive options are okay
        if not line.strip():
            continue
        # Non-indented non-blank line means directive ended
        if not (line.startswith(" ") or line.startswith("\t")):
            break
        # This indented line is part of the directive
        end_line = i + 1
    
    return end_line


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
            f"insert_doto_directive: task_data must contain 'id'. "
            f"Got: {list(task_data.keys())}"
        )
    
    if not rst_file.exists():
        # Create file with just the directive
        try:
            directive_text = generate_directive_text(task_data)
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


def _find_directive_block(content: str, task_id: str) -> tuple[int, int, str] | None:
    """Find a doto directive block by task ID.
    
    Uses docutils to properly parse the RST and identify directive boundaries,
    handling nested content correctly.
    
    Args:
        content: Full file content.
        task_id: Task ID to find.
        
    Returns:
        Tuple of (start_pos, end_pos, directive_content) or None if not found.
        
    Raises:
        DotoValidationError: If task_id is empty.
    """
    if not content:
        return None
    
    if not task_id:
        raise DotoValidationError("task_id cannot be empty")
    
    boundaries = _find_directive_boundaries(content, task_id)
    if boundaries is None:
        return None
    
    start_pos, end_pos = boundaries
    
    # Validate boundaries
    if start_pos < 0 or end_pos > len(content) or start_pos >= end_pos:
        return None
    
    return start_pos, end_pos, content[start_pos:end_pos]


def _update_directive_content(directive_content: str, updates: dict[str, Any]) -> str:
    """Update fields within a directive's content.
    
    Args:
        directive_content: The current directive text.
        updates: Fields to update.
        
    Returns:
        Updated directive text.
    """
    from doxtr_doto.fields import FIELD_NAME_TO_RST
    
    lines = directive_content.split("\n")
    result = []
    
    # Track which fields we've updated
    updated_fields = set()
    
    # Use central field registry for name mapping
    field_map = FIELD_NAME_TO_RST
    
    for line in lines:
        updated = False
        for field, value in updates.items():
            rst_field = field_map.get(field, field)
            pattern = rf"^(\s+):{rst_field}:\s*.*$"
            match = re.match(pattern, line)
            if match:
                # Update this field - use the captured indent from the match
                indent = match.group(1)
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                result.append(f"{indent}:{rst_field}: {value}")
                updated_fields.add(field)
                updated = True
                break
        
        if not updated:
            result.append(line)
    
    # Add any new fields that weren't in the original
    # Find the indentation from existing options
    option_indent = "   "  # Default (3 spaces for RST)
    for line in result:
        option_match = re.match(r"^(\s+):[a-z-]+:", line)
        if option_match:
            option_indent = option_match.group(1)
            break
    
    # Insert new fields after existing options, before body
    insert_pos = len(result)
    for i, line in enumerate(result):
        stripped = line.strip()
        # Find first non-option, non-directive line with content
        if stripped and not stripped.startswith(":") and not stripped.startswith(".. doto::"):
            insert_pos = i
            break
    
    for field, value in updates.items():
        if field not in updated_fields:
            rst_field = field_map.get(field, field)
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            if value:  # Only add if value is not empty
                result.insert(insert_pos, f"{option_indent}:{rst_field}: {value}")
                insert_pos += 1
    
    return "\n".join(result)


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
) -> str:
    """Apply an in-place directive update to RST content string.
    
    Returns modified content. Does not read or write any file.
    
    Args:
        content: Full RST file content.
        task_id: The task ID to update.
        updates: Fields to update.
        
    Returns:
        Updated content string (unchanged if task not found).
    """
    directive_match = _find_directive_block(content, task_id)
    if directive_match is None:
        return content
    
    start, end, directive_content = directive_match
    updated = _update_directive_content(directive_content, updates)
    return content[:start] + updated + content[end:]


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
    directive_text = generate_directive_text(task_data)
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
