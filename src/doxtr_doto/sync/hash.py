"""RST content hashing for change detection."""

from __future__ import annotations

import hashlib
import re


def normalize_rst_directive(content: str) -> str:
    """Normalize RST directive content for consistent hashing.

    Strips leading/trailing whitespace and normalizes internal whitespace
    to ensure minor formatting differences don't cause spurious changes.

    Args:
        content: Raw RST directive content.

    Returns:
        Normalized content string.
    """
    # Strip leading/trailing whitespace
    content = content.strip()

    # Normalize line endings to Unix style
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize multiple spaces to single space (except at line start for indentation)
    lines = []
    for line in content.split("\n"):
        # Preserve leading whitespace (indentation), normalize trailing
        stripped = line.rstrip()
        if stripped:
            # Find leading whitespace
            leading = len(line) - len(line.lstrip())
            # Normalize multiple spaces in the content part to single space
            normalized_content = re.sub(r"[ \t]+", " ", line[leading:].strip())
            lines.append(line[:leading] + normalized_content)
        else:
            lines.append("")

    # Remove multiple consecutive blank lines
    result = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    return "\n".join(result)


def compute_rst_hash(directive_content: str) -> str:
    """Compute hash of a doto directive's content for change detection.

    Normalizes whitespace before hashing to avoid spurious conflicts
    from formatting-only changes.

    Args:
        directive_content: The raw content of the doto directive.

    Returns:
        SHA-256 hash truncated to 16 characters.
    """
    normalized = normalize_rst_directive(directive_content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
