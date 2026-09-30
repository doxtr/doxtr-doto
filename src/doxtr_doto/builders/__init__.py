"""Builders for doto extension.

This package contains the virtual archive document builder.
"""

from __future__ import annotations

from doxtr_doto.builders.archive_doc import (
    add_archive_doc,
    cleanup_virtual_docs,
    generate_archive_content,
    inject_archive_doc,
    read_virtual_doc,
)

__all__ = [
    "add_archive_doc",
    "cleanup_virtual_docs",
    "generate_archive_content",
    "inject_archive_doc",
    "read_virtual_doc",
]
