"""Provider-agnostic calendar sync engine (push-first).

Given the set of doto tasks, the persisted sync state, and a connected
provider, the engine computes a :class:`SyncPlan` of create/update/delete/skip
actions and (optionally) applies it. ``push`` is the only direction implemented
today; the engine is structured so a future two-way mode can add a pull pass
without rewriting the planning logic.

Planning rules (push):

* A task with a ``due`` and a schedulable status is projected to an event.
  - No prior state  -> CREATE
  - State exists, content hash changed -> UPDATE
  - State exists, hash unchanged        -> SKIP
* A previously-synced task that no longer qualifies (archived, due removed, or
  now excluded) -> DELETE its remote item and drop its state.

Only items doto itself created (recognizable by the ``doto-`` UID prefix and
tracked in state) are ever updated or deleted; user-created calendar entries
are never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from doxtr_doto.calsync.ical import content_hash
from doxtr_doto.calsync.model import make_uid, project
from doxtr_doto.calsync.state import RemoteRef

if TYPE_CHECKING:
    from doxtr_doto.calsync.providers.base import CalendarProvider
    from doxtr_doto.calsync.state import CalSyncState
    from doxtr_doto.cli.config import CalendarConfig


class Action(str, Enum):
    """A planned sync action for one task."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SKIP = "skip"


#: Task statuses that should NOT appear on the calendar. "done" tasks are kept
#: by default (a completed deadline is still useful history) but can be excluded
#: by callers; archived tasks are always excluded upstream.
_DEFAULT_EXCLUDE_STATUSES: set[str] = set()


@dataclass
class PlanItem:
    """One planned action.

    Attributes:
        task_id: The doto task id.
        action: What will happen (create/update/delete/skip).
        uid: The item's stable UID.
        reason: Short human-readable justification (for the dry-run output).
        event: The projected event (None for DELETE/SKIP-without-event).
    """

    task_id: str
    action: Action
    uid: str
    reason: str = ""
    event: Any = None


@dataclass
class SyncPlan:
    """The full set of planned actions."""

    items: list[PlanItem] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return a ``{action: count}`` summary."""
        out = {a.value: 0 for a in Action}
        for item in self.items:
            out[item.action.value] += 1
        return out

    def actionable(self) -> list[PlanItem]:
        """Return only items that change the remote (not SKIP)."""
        return [i for i in self.items if i.action is not Action.SKIP]


@dataclass
class SyncReport:
    """Outcome of applying a plan."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)  # (task_id, message)

    def total_changes(self) -> int:
        return self.created + self.updated + self.deleted


def _is_schedulable(task: dict[str, Any], exclude_statuses: set[str]) -> bool:
    """Whether a task should be present on the calendar."""
    if task.get("archived"):
        return False
    if not task.get("due"):
        return False
    status = str(task.get("status") or "open")
    return status not in exclude_statuses


def build_plan(
    tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
    *,
    repo_name: str = "",
    exclude_statuses: set[str] | None = None,
) -> SyncPlan:
    """Compute the create/update/delete/skip plan for a push sync.

    Args:
        tasks: Mapping of task_id -> task data (active tasks to consider).
        state: Loaded sync state for change detection.
        cal: Resolved calendar config (provider, calendar, projection knobs).
        repo_name: Optional repo name used to build the back-reference label.
        exclude_statuses: Statuses to keep off the calendar (default: none).

    Returns:
        A :class:`SyncPlan`.
    """
    exclude = exclude_statuses if exclude_statuses is not None else _DEFAULT_EXCLUDE_STATUSES
    provider = cal.provider
    calendar = cal.calendar
    plan = SyncPlan()

    seen: set[str] = set()
    for task_id, task in tasks.items():
        seen.add(task_id)
        prior = state.get(provider, calendar, task_id)

        if not _is_schedulable(task, exclude):
            if prior is not None:
                plan.items.append(
                    PlanItem(
                        task_id=task_id,
                        action=Action.DELETE,
                        uid=prior.uid,
                        reason="no longer schedulable (archived / no due / excluded)",
                    )
                )
            continue

        ref = f"{repo_name}#{task_id}" if repo_name else task_id
        try:
            event = project(task_id, task, cal, back_reference=ref)
        except ValueError as exc:
            # Shouldn't happen (we checked due), but be defensive.
            plan.items.append(
                PlanItem(
                    task_id=task_id,
                    action=Action.SKIP,
                    uid=make_uid(task_id),
                    reason=f"projection error: {exc}",
                )
            )
            continue

        new_hash = content_hash(event)
        if prior is None:
            plan.items.append(PlanItem(task_id, Action.CREATE, event.uid, "new task", event))
        elif prior.content_hash != new_hash:
            plan.items.append(PlanItem(task_id, Action.UPDATE, event.uid, "task changed", event))
        else:
            plan.items.append(PlanItem(task_id, Action.SKIP, event.uid, "unchanged", event))

    # Tasks that were synced before but are gone from the store entirely
    # (deleted) must have their remote items removed too.
    for task_id in state.task_ids(provider, calendar):
        if task_id in seen:
            continue
        prior = state.get(provider, calendar, task_id)
        if prior is not None:
            plan.items.append(
                PlanItem(task_id, Action.DELETE, prior.uid, "task deleted from store")
            )

    return plan


def apply_plan(
    plan: SyncPlan,
    provider: CalendarProvider,
    state: CalSyncState,
    cal: CalendarConfig,
) -> SyncReport:
    """Apply ``plan`` against a connected ``provider``, updating ``state``.

    Each item is applied independently; a failure on one task is recorded in
    the report and does not abort the rest. State is mutated in-memory; callers
    are responsible for calling ``state.save()`` afterwards.

    Args:
        plan: The plan from :func:`build_plan`.
        provider: A connected provider.
        state: Sync state to update as items succeed.
        cal: Calendar config (provides provider/calendar namespace keys).

    Returns:
        A :class:`SyncReport`.
    """
    report = SyncReport()
    now = datetime.now().isoformat()
    pname = cal.provider
    cname = cal.calendar

    for item in plan.items:
        try:
            if item.action is Action.SKIP:
                report.skipped += 1
                continue
            if item.action is Action.CREATE:
                result = provider.create_event(item.event)
                state.set(
                    pname,
                    cname,
                    item.task_id,
                    RemoteRef(
                        uid=result.uid,
                        etag=result.etag,
                        href=result.href,
                        content_hash=content_hash(item.event),
                        remote_id=result.remote_id,
                        updated=now,
                    ),
                )
                report.created += 1
            elif item.action is Action.UPDATE:
                prior = state.get(pname, cname, item.task_id)
                result = provider.update_event(
                    item.event,
                    etag=prior.etag if prior else "",
                    href=(prior.remote_id or prior.href) if prior else "",
                )
                state.set(
                    pname,
                    cname,
                    item.task_id,
                    RemoteRef(
                        uid=result.uid,
                        etag=result.etag,
                        href=result.href,
                        content_hash=content_hash(item.event),
                        remote_id=result.remote_id,
                        updated=now,
                    ),
                )
                report.updated += 1
            elif item.action is Action.DELETE:
                prior = state.get(pname, cname, item.task_id)
                provider.delete_event(
                    item.uid,
                    etag=prior.etag if prior else "",
                    href=(prior.remote_id or prior.href) if prior else "",
                )
                state.delete(pname, cname, item.task_id)
                report.deleted += 1
        except Exception as exc:  # provider errors are per-item recoverable
            report.errors.append((item.task_id, str(exc)))

    return report
