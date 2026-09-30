"""Virtual archive document builder for archived tasks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from doxtr_doto.types import (
    add_doto_temp_file,
    get_doto_temp_files,
    get_doto_virtual_docs,
    set_doto_virtual_doc,
)

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment


def add_archive_doc(
    app: Sphinx,
    env: BuildEnvironment,
    added: set[str],
    changed: set[str],
    removed: set[str],
) -> list[str]:
    """
    Add the virtual archive document to the build if needed.
    
    Called via env-get-outdated event.
    Returns list of additional docnames to process.
    """
    from doxtr_doto.collectors import get_doto_env
    from doxtr_doto.config import get_config
    
    if not get_config(app, "auto_archive"):
        return []
    
    archive_doc = get_config(app, "archive_doc")
    doto_env = get_doto_env(env)
    
    # Check if we have any archived tasks
    has_archived = any(
        task.archived for task in doto_env.all_tasks.values()
    )
    
    if has_archived:
        # Add archive doc to be processed
        return [archive_doc]
    
    return []


def inject_archive_doc(
    app: Sphinx,
    env: BuildEnvironment,
    docnames: list[str],
) -> None:
    """
    Inject the virtual archive document content.
    
    Called via env-before-read-docs event.
    Creates a temporary RST file in the source directory that will be
    cleaned up after build. This ensures Sphinx can read the file normally.
    """
    from doxtr_doto.config import get_config
    
    if not get_config(app, "auto_archive"):
        return
    
    archive_doc = get_config(app, "archive_doc")
    
    if archive_doc not in docnames:
        return
    
    # Generate the archive document content
    content = generate_archive_content(app, env)
    
    # Create the actual file (will be cleaned up in build-finished)
    archive_path = Path(app.srcdir) / f"{archive_doc}.rst"
    
    # Only create if it doesn't already exist (user might have their own)
    if not archive_path.exists():
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(content, encoding="utf-8")
        # Track for cleanup
        add_doto_temp_file(env, archive_path)
    
    # Also store in virtual docs for backward compatibility
    set_doto_virtual_doc(env, archive_doc, content)


def generate_archive_content(app: Sphinx, env: BuildEnvironment) -> str:
    """
    Generate RST content for the archive page.
    
    Args:
        app: Sphinx application
        env: Build environment
    
    Returns:
        RST content for the archive document
    """
    from doxtr_doto.collectors import get_doto_env
    
    doto_env = get_doto_env(env)
    
    # Collect archived tasks
    archived_tasks = [
        task for task in doto_env.all_tasks.values()
        if task.archived
    ]
    
    # Sort by archived_on date (most recent first)
    archived_tasks.sort(
        key=lambda t: t.archived_on or t.updated or t.created,
        reverse=True,
    )
    
    # Generate RST content
    lines = [
        "Archived Tasks",
        "==============",
        "",
        "This page contains tasks that have been archived.",
        "",
        f"**Total archived tasks:** {len(archived_tasks)}",
        "",
    ]
    
    if archived_tasks:
        lines.append(".. doto-list::")
        lines.append("   :show-archived: true")
        lines.append("   :status: done")
        lines.append("   :sort: updated")
        lines.append("   :format: table")
        lines.append("")
    else:
        lines.append("*No archived tasks.*")
        lines.append("")
    
    return "\n".join(lines)


def get_archive_doc_content(env: BuildEnvironment, docname: str) -> str | None:
    """
    Get virtual document content if available.
    
    Args:
        env: Build environment
        docname: Document name to check
    
    Returns:
        Virtual document content or None
    """
    virtual_docs = get_doto_virtual_docs(env)
    return virtual_docs.get(docname)


def read_virtual_doc(
    app: Sphinx,
    docname: str,
    source: list[str],
) -> None:
    """
    Provide virtual document content via source-read event.
    
    This handler intercepts the source-read event and replaces the source
    content with virtual document content when the docname matches a
    virtual document stored in env.doto_virtual_docs.
    
    Note: With the temp file approach, this handler is kept for backward
    compatibility but the temp file should be read by Sphinx normally.
    
    Args:
        app: Sphinx application
        docname: Name of the document being read
        source: List containing the source content (modified in place)
    """
    env = app.env
    if env is None:
        return
    
    content = get_archive_doc_content(env, docname)
    if content is not None:
        # Replace the source content with our virtual document
        source[0] = content


def cleanup_virtual_docs(app: Sphinx, exception: Exception | None) -> None:
    """Clean up temporary virtual document files after build.
    
    Connected to build-finished event with priority=900 (run late).
    
    Args:
        app: Sphinx application instance.
        exception: Exception if build failed, None otherwise.
    """
    env = app.env
    if env is None:
        return
    
    temp_files = get_doto_temp_files(env)
    
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                temp_file.unlink()
                # Also remove parent dir if empty and it's not the srcdir
                parent = temp_file.parent
                if parent != Path(app.srcdir) and parent.exists():
                    try:
                        # Only remove if empty
                        if not any(parent.iterdir()):
                            parent.rmdir()
                    except OSError:
                        pass  # Directory not empty or other error
        except OSError:
            pass  # Ignore cleanup errors
    
    # Clear the list
    temp_files.clear()
