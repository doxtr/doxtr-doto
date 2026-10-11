"""Shared cross-repo task-session collector.

A single importable helper that gathers ``(repo, task_id, title, worklogs)``
tuples across the current project store plus every registered repository,
ready to feed into :func:`doxtr_doto.work_report.compute_task_breakdown`.

Factored out of :mod:`doxtr_doto.cli.commands.report` so both the ``doto
report`` CLI command and the TUI per-doto time-reporting surface use the exact
same collection logic (no duplication): the CLI command imports and calls
:func:`collect_repo_tasks`, and the TUI's per-doto stats modal imports it
directly. The behavior is unchanged from the CLI's original ``_collect_tasks``
(current project first, then each registered repo, de-duplicated by store
path, tasks without worklogs skipped, unreadable stores skipped silently).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from doxtr_doto.cli.repo_registry import RepoRegistry

if TYPE_CHECKING:
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.sync.json_store import WorkLog


def collect_repo_tasks(
    ctx: DotoContext,
) -> list[tuple[str, str, str, list[WorkLog]]]:
    """Gather ``(repo, task_id, title, worklogs)`` across all repos.

    Includes the current project store plus every registered repository.
    Stores are de-duplicated by their absolute path (so a current repo that
    also appears in the discovery cache is only read once), tasks without any
    worklogs are skipped (they contribute no session time), and a repo whose
    store cannot be read is skipped silently.

    This is the single source of truth for the cross-repo task-session
    collection used by both ``doto report`` and the TUI per-doto time
    reporting surface, so the two can never diverge.

    Args:
        ctx: The CLI context.

    Returns:
        Flat list of ``(repo, task_id, title, worklogs)`` task tuples with
        worklogs, ready for
        :func:`doxtr_doto.work_report.compute_task_breakdown`.
    """
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.session import derive_repo_name

    seen_paths: set[str] = set()
    tasks: list[tuple[str, str, str, list[WorkLog]]] = []

    def _ingest(repo_name: str, store: JsonTaskStore) -> None:
        path = str(store.path)
        if path in seen_paths:
            return
        seen_paths.add(path)
        try:
            all_tasks = store.get_all_tasks()
        except Exception:
            return
        for task_id, task in all_tasks.items():
            worklogs = task.get("worklogs") or []
            if not worklogs:
                continue
            tasks.append((repo_name, task_id, task.get("title", ""), worklogs))

    # Current project first.
    _ingest(derive_repo_name(ctx.config), ctx.store)

    # Then every registered repo.
    for repo in RepoRegistry(ctx.global_store).list_repos():
        json_path = Path(repo.path) / ".doto" / "tasks.json"
        if not json_path.exists():
            continue
        _ingest(repo.name, JsonTaskStore(json_path))

    return tasks
