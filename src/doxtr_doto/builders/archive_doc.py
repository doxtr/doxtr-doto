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


def _collect_archived_tasks_from_store(
    app: Sphinx,
    env: BuildEnvironment,
) -> list[Any]:
    """Return archived tasks sourced from the JSON store, newest first.

    The archive page is sourced from the JSON task store (``.doto/tasks.json``),
    not from ``doto_env.all_tasks``: an archived task's ``.. doto::`` directive
    is removed from its RST file, so ``all_tasks`` (populated only from parsed
    RST directives) no longer contains it on any build after the archiving one.
    Reading the store directly means the archive page reflects every archived
    task regardless of whether its directive still exists in RST.

    Any archived tasks still present in ``all_tasks`` (e.g. during the very
    build that archives them) are merged in and de-duplicated by task id, with
    the JSON store copy preferred as the source of truth. A missing/absent JSON
    file is handled gracefully (empty list, no crash).

    Args:
        app: Sphinx application instance.
        env: Build environment.

    Returns:
        Archived :class:`~doxtr_doto.collectors.DotoTask` objects sorted by
        archive date descending (newest first).
    """
    from doxtr_doto.collectors import DotoTask, get_doto_env
    from doxtr_doto.config import get_config
    from doxtr_doto.sync.json_store import JsonTaskStore

    by_id: dict[str, Any] = {}

    json_file = get_config(app, "json_file")
    json_path = Path(app.srcdir) / json_file
    if json_path.exists():
        try:
            store = JsonTaskStore(json_path)
            store.load()
            for task_id, data in store.iter_archived_tasks():
                by_id[task_id] = DotoTask.from_dict(task_id, data)
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt/unreadable store: fall back to env-only below.
            pass

    doto_env = get_doto_env(env)
    for task in doto_env.all_tasks.values():
        if getattr(task, "archived", False) and task.id not in by_id:
            by_id[task.id] = task

    archived = list(by_id.values())
    archived.sort(key=_archive_date_key, reverse=True)
    return archived


def _archive_date_key(task: Any) -> str:
    """Return a type-homogeneous sort key for an archived task.

    Falls back through ``archived_on`` -> ``updated`` -> ``created``, coercing
    whichever is first present to a string so mixed ``datetime``/``str``/``None``
    date values never raise a ``TypeError`` during sorting. Tasks with no dates
    sort last (empty string).

    Args:
        task: Archived DotoTask (or compatible object).

    Returns:
        An ISO-8601-ish string (or "" when the task has no dates).
    """
    for attr in ("archived_on", "updated", "created"):
        value = getattr(task, attr, None)
        if value is None:
            continue
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)
    return ""


def add_archive_doc(
    app: Sphinx,
    env: BuildEnvironment,
    added: set[str],
    changed: set[str],
    removed: set[str],
) -> list[str]:
    """
    Add the virtual archive document to the build if needed.

    Called via env-get-outdated event. The "has archived tasks" decision is
    based on the JSON task store (merged with any archived tasks still in the
    environment), not ``all_tasks`` alone, so the archive doc is added whenever
    archived tasks exist in ``.doto/tasks.json`` even though their directives
    have been removed from RST.

    Returns list of additional docnames to process.
    """
    from doxtr_doto.config import get_config

    if not get_config(app, "auto_archive"):
        return []

    archive_doc = get_config(app, "archive_doc")

    # Check if we have any archived tasks (JSON store is the source of truth).
    has_archived = bool(_collect_archived_tasks_from_store(app, env))

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

    The archived-task count and the empty-state decision are based on the JSON
    task store (``.doto/tasks.json``), not ``all_tasks``, so the page renders
    the ``.. doto-archive::`` directive whenever archived tasks exist in the
    store even though their directives have been removed from their RST files.

    Args:
        app: Sphinx application
        env: Build environment

    Returns:
        RST content for the archive document
    """
    # Collect archived tasks from the JSON store (source of truth).
    archived_tasks = _collect_archived_tasks_from_store(app, env)

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
        # Render from the JSON store via the dedicated doto-archive directive
        # (see directives/doto_archive.py). This keeps the archive page sourced
        # from the task store and child-theme overridable via the template
        # system, instead of relying on a plain doto-list over RST data.
        lines.append(".. doto-archive::")
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
