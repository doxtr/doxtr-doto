"""Daily kickstart-nudge decision logic for the doto TUI.

This module holds the *decision* half of requirement 5 (the once-per-day
kickstart nudge) deliberately separated from the modal widget so it can be
unit-tested without rendering a Textual screen.

Responsibilities:

* decide whether the nudge should fire on launch
  (:func:`should_show_nudge`),
* gather the top candidate tasks to offer as one-key shortcuts
  (:func:`gather_candidates`),
* record that the nudge was shown so it fires at most once per day
  (:func:`mark_prompted`).

The modal screen (:class:`doxtr_doto.cli.tui.app.KickstartScreen`) consumes
these helpers; it never re-implements the dedupe or scoring rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from doxtr_doto.cli.commands.next import calculate_task_score, get_ready_tasks
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.id_resolver import namespaced_id
from doxtr_doto.cli.tui import data
from doxtr_doto.time_tracking import has_open_session

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext

#: How many candidate tasks the nudge offers one-key shortcuts for.
MAX_CANDIDATES = 3


def today_iso(today: date | None = None) -> str:
    """Return today's date as an ISO ``YYYY-MM-DD`` string.

    Args:
        today: Reference date (defaults to the current local date).

    Returns:
        The ISO-formatted date string.
    """
    return (
        today if today is not None else datetime.now(timezone.utc).astimezone().date()
    ).isoformat()


def has_active_focus(ctx: DotoContext) -> bool:
    """Return whether a focus timer is currently running.

    A focus timer is "active" when the global state records an active focus
    session whose task still has an open worklog. This mirrors the resolution
    used by :func:`doxtr_doto.cli.tui.data.live_counters` so the nudge and the
    status line agree.

    Args:
        ctx: The CLI context.

    Returns:
        True if a focus session is open, False otherwise.
    """
    state = ctx.global_store.load()
    session = state.active_session
    if not session or not session.get("task_id"):
        return False
    from doxtr_doto.cli.session import resolve_session_store

    store = resolve_session_store(ctx.store, session.get("json_path"))
    task = store.get_task(session["task_id"])
    if task is None:
        return False
    return has_open_session(task.get("worklogs", []))


def should_show_nudge(
    last_prompt_date: str | None,
    focus_active: bool,
    today: str,
) -> bool:
    """Decide whether the daily kickstart nudge should fire.

    The nudge fires at most once per day and only when the user has not
    already started working. Concretely it fires when *both* conditions hold:

    * the user has not been prompted today
      (``last_prompt_date != today``), and
    * no focus timer is currently active (``focus_active`` is False).

    Keeping this a pure function (no I/O) makes the date-boundary and
    timer-suppression rules unit-testable without rendering the modal.

    Args:
        last_prompt_date: The stored ISO date of the last nudge, or None.
        focus_active: Whether a focus timer is currently running.
        today: Today's ISO date string.

    Returns:
        True if the nudge should be shown, False otherwise.
    """
    if focus_active:
        return False
    return last_prompt_date != today


@dataclass(frozen=True)
class Candidate:
    """A kickstart candidate task offered as a one-key shortcut.

    Attributes:
        key: The one-key shortcut digit (``"1"``, ``"2"``, ...).
        ref: The canonical task reference to start (``repo#id``, or a bare id
            when the task has no owning repo). Deliberately independent of the
            shortened display id so the ref always resolves to the owning repo.
        title: The task title for display.
        priority: The task priority for display.
    """

    key: str
    ref: str
    title: str
    priority: str


def gather_candidates(
    ctx: DotoContext,
    limit: int = MAX_CANDIDATES,
) -> list[Candidate]:
    """Gather the top kickstart candidate tasks across the registry.

    Reuses :func:`doxtr_doto.cli.commands.next.get_ready_tasks` /
    :func:`~doxtr_doto.cli.commands.next.calculate_task_score` to rank
    candidates with the same scoring ``doto next`` uses.

    Dependency penalties in :func:`calculate_task_score` look ``depends_on``
    ids up in the scoring dict. ``depends_on`` stores *bare* ids, so the
    scoring dict must be keyed by bare id for the lookups to match. We
    therefore score each repository against its own bare-id-keyed task set so
    same-repo dependency penalties are honored, then merge and re-rank the
    per-repo results. (Cross-repo ``repo#id`` dependencies are out of scope:
    ``depends_on`` has no repo component, so a bare dep id is only meaningful
    within its own repo.)

    Args:
        ctx: The CLI context.
        limit: Maximum number of candidates to return.

    Returns:
        Up to ``limit`` :class:`Candidate` entries, highest-priority first.
    """
    tasks = data.gather_tasks(ctx, DisplayScope.GLOBAL)

    # Group tasks by owning repo so dependency lookups (bare ids) resolve
    # within the same repo's task set. The ACTION ref is built from the
    # preserved _repo / _local_id tags as a canonical ``repo#id``, NOT from
    # the (possibly shortened) display id: apply_scope shortens the display
    # id to a bare id when a base prefix is unique in the view, and a bare id
    # resolves against the current repo's store — so using it as the ref would
    # misresolve a foreign repo's task. Keep this ref canonical.
    by_repo: dict[str, dict[str, dict[str, Any]]] = {}
    canonical_refs: dict[tuple[str, str], str] = {}
    for task in tasks:
        repo = str(task.get("_repo", ""))
        local_id = str(task.get("_local_id", task.get("id", "")))
        by_repo.setdefault(repo, {})[local_id] = task
        canonical_refs[(repo, local_id)] = namespaced_id(repo, local_id) if repo else local_id

    # Score each repo independently, then merge the ranked results.
    scored: list[tuple[tuple[int, str, str], str, Mapping[str, Any]]] = []
    for repo, repo_tasks in by_repo.items():
        for local_id, ready_task, score in get_ready_tasks(repo_tasks):
            ref = canonical_refs[(repo, local_id)]
            scored.append((score, ref, ready_task))

    # Re-rank across repos by the same key get_ready_tasks uses:
    # score descending, then due date, then id.
    scored.sort(key=lambda item: (-item[0][0], item[0][1], item[1]))

    candidates: list[Candidate] = []
    for index, (_score, ref, ranked_task) in enumerate(scored[:limit], start=1):
        candidates.append(
            Candidate(
                key=str(index),
                ref=ref,
                title=str(ranked_task.get("title", ref)),
                priority=str(ranked_task.get("priority", "medium")),
            )
        )
    return candidates


def mark_prompted(ctx: DotoContext, today: str | None = None) -> None:
    """Record that the kickstart nudge was shown today.

    Writes ``last_prompt_date`` into the global config so the nudge fires at
    most once per day, regardless of which choice the user made (including
    skipping). The write is atomic (handled by the global store).

    Args:
        ctx: The CLI context.
        today: Today's ISO date (defaults to the current local date).
    """
    stamp = today if today is not None else today_iso()
    state = ctx.global_store.load()
    state.last_prompt_date = stamp
    ctx.global_store.save(state)


# Re-exported so callers can reference the scorer alongside the gather helper.
__all__ = [
    "Candidate",
    "MAX_CANDIDATES",
    "calculate_task_score",
    "gather_candidates",
    "has_active_focus",
    "mark_prompted",
    "should_show_nudge",
    "today_iso",
]
