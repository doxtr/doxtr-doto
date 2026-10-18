"""Provider-agnostic calendar sync engine (push + pull / two-way).

Given the set of doto tasks, the persisted sync state, and a connected
provider, the engine computes a plan of actions and (optionally) applies it.
Two directions are supported:

* **push** (doto -> calendar): the original, default direction.
* **pull** (calendar -> doto): import user-created events and reconcile
  previously-imported ones (used by ``direction = "two-way"``).

Planning rules (push):

* A task with a ``due`` and a schedulable status is projected to an event.
  - No prior state  -> CREATE
  - State exists, content hash changed -> UPDATE
  - State exists, hash unchanged        -> SKIP
* A previously-synced task that no longer qualifies (archived, due removed, or
  now excluded) -> DELETE its remote item and drop its state.

Only items doto itself created (recognizable by the ``doto-`` UID prefix and
tracked in state) are ever updated or deleted; user-created calendar entries
are never touched by push.

Planning rules (pull):

* A remote event whose UID is **doto-owned** (``is_doto_uid``) is ignored by
  pull -- those round-trip through push, and re-importing them would duplicate
  tasks. (A conflicting local+remote edit of a doto-owned item is resolved by
  the two-way orchestration, see below.)
* A **new** remote event that is *not* doto-owned (created directly in the
  calendar by the user or another tool) is IMPORTED as a new local task
  (``IMPORT``): summary -> title, description -> body (the ``[doto:...]``
  back-reference line, if any, is stripped), start/due -> ``due``
  (date-only for all-day, keeping the time otherwise), status open. The remote
  item is tracked in state by its iCalUID so a second pull is a no-op (SKIP).
* An imported remote event that **changed** since the last pull updates the
  local task's title/body/due (``UPDATE_LOCAL``).
* A previously-imported remote event that is now **gone** from the calendar is
  taken as a user deletion and the local task is ARCHIVED (``ARCHIVE_LOCAL``),
  never hard-deleted, so the data is recoverable.

Two-way orchestration and ordering (:func:`two_way_sync`):

Pull runs **first**, then push. Pulling first means user-created events become
tasks before push computes its plan, so a freshly imported task is not treated
as "deleted from the store" by the push pass. Push then reconciles doto-owned
items as usual.

Conflict policy (local edit vs. remote edit of the *same doto-owned item*):
**local-wins** by default. doto is the system of record for its own items, so
when both a local task and its doto-owned remote event changed since the last
sync (the local projected hash differs from the stored outbound hash *and* the
live remote inbound hash differs from the stored inbound baseline), pull leaves
the local task untouched and the subsequent push overwrites the remote with the
local state. The conflict is recorded in the report (``conflicts``) so callers
can surface a warning. This is deterministic and never loses local work; the
remote edit is discarded in favor of the local one.

Extension seams (all mirror :func:`doxtr_doto.calsync.model.register_projector`
so a downstream can customize behavior without editing core or any provider):

* :func:`register_inbound_mapper` swaps the RemoteEvent -> task-fields mapping
  used by pull (the inbound counterpart to ``register_projector``).
* :func:`two_way_sync`'s ``conflict_policy`` parameter injects a
  :data:`ConflictPolicy` callable (default :func:`local_wins_policy`) so a
  downstream can select remote-wins / newest-wins without editing
  ``two_way_sync``. Only :data:`ConflictResolution.LOCAL_WINS` is wired into
  the built-in orchestration today; a non-default policy currently changes only
  what is reported.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from doxtr_doto.calsync.ical import content_hash, inbound_hash_of_pushed, remote_content_hash
from doxtr_doto.calsync.model import (
    BACK_REFERENCE_CLOSE,
    BACK_REFERENCE_OPEN,
    is_doto_uid,
    make_uid,
    project,
    task_id_from_uid,
    timed_duration_minutes,
)
from doxtr_doto.calsync.state import ImportedRef, RemoteRef

if TYPE_CHECKING:
    from doxtr_doto.calsync.model import CalendarEvent, RemoteEvent
    from doxtr_doto.calsync.providers.base import CalendarProvider
    from doxtr_doto.calsync.state import CalSyncState
    from doxtr_doto.calsync.textmerge import MergeOutcome
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
    skip_task_ids: set[str] | None = None,
) -> SyncPlan:
    """Compute the create/update/delete/skip plan for a push sync.

    Args:
        tasks: Mapping of task_id -> task data (active tasks to consider).
        state: Loaded sync state for change detection.
        cal: Resolved calendar config (provider, calendar, projection knobs).
        repo_name: Optional repo name used to build the back-reference label.
        exclude_statuses: Statuses to keep off the calendar (default: none).
        skip_task_ids: Task ids the push pass must leave alone -- tasks that
            *originate* from the calendar (imported by pull). Pushing them
            would create a duplicate doto-owned event alongside the user's
            original. Only tasks doto itself created and tracks for push
            (``namespaces``) are managed here. A skipped task that *also* has
            a prior push ref is still reconciled (it was pushed before it was
            ever imported, which should not normally happen) so state does not
            silently diverge.

    Returns:
        A :class:`SyncPlan`.
    """
    exclude = exclude_statuses if exclude_statuses is not None else _DEFAULT_EXCLUDE_STATUSES
    skip = skip_task_ids or set()
    provider = cal.provider
    calendar = cal.calendar
    plan = SyncPlan()

    seen: set[str] = set()
    for task_id, task in tasks.items():
        seen.add(task_id)
        prior = state.get(provider, calendar, task_id)

        # A task imported from the calendar must not be pushed back up as a
        # new doto-owned event -- it already exists remotely as the user's
        # item. Skip it unless doto previously pushed it (prior ref present),
        # in which case normal reconciliation still applies.
        if task_id in skip and prior is None:
            plan.items.append(
                PlanItem(
                    task_id=task_id,
                    action=Action.SKIP,
                    uid=make_uid(task_id),
                    reason="imported from calendar (owned by pull)",
                )
            )
            continue

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


def _inbound_due_of_event(event: CalendarEvent) -> str:
    """Inbound-equivalent ISO due string for a projected event.

    Mirrors :func:`~doxtr_doto.calsync.ical.inbound_hash_of_pushed` /
    :meth:`RemoteEvent.inbound_due` so the stored merge baseline lines up with
    both the local task's ``due`` and a remote read-back. Returns ``""`` when
    the event has no anchor.
    """
    from doxtr_doto.date_utils import DotoDate

    anchor = event.due or event.start
    if anchor is None:
        return ""
    if event.all_day:
        return anchor.date().isoformat()
    return DotoDate(anchor.date(), anchor.time()).isoformat()


def _base_snapshot_from_event(
    event: CalendarEvent, cal: CalendarConfig
) -> tuple[str, str, str, str]:
    """Derive the (title, body, due, estimate) merge baseline from a pushed event.

    The three-way merge conflict policy needs the *last-synced* values as a
    common ancestor. We snapshot them from the event doto just pushed, in the
    same inbound-equivalent form the merge compares against: ``summary`` as the
    title, the ``description`` with the trailing ``[doto:...]`` back-reference
    stripped (so it matches the local ``body`` and an inbound-stripped remote
    body), the inbound ISO due, and the timed-event duration as a compact
    estimate string.

    The estimate baseline mirrors the inbound mapper
    (:func:`_task_fields_from_remote`): a duration equal to the calendar's
    ``event_duration_minutes`` is recorded as **empty**, because that is the
    round-trip of a task that had *no* estimate (push defaults the slot size).
    Recording it empty keeps base == local for such a task, so a later remote
    resize is seen as a remote-only change and flows back cleanly.
    """
    from doxtr_doto.date_utils import format_duration_minutes

    minutes = _non_default_estimate_minutes(
        timed_duration_minutes(event.all_day, event.start, event.end), cal
    )
    estimate = format_duration_minutes(minutes) if minutes is not None else ""
    return (
        event.summary or "",
        _strip_back_reference(event.description or ""),
        _inbound_due_of_event(event),
        estimate,
    )


def _non_default_estimate_minutes(minutes: int | None, cal: CalendarConfig | None) -> int | None:
    """Collapse a timed-event duration to an estimate, or None when it's the default.

    The single source of truth for the mapping rule "a duration equal to the
    calendar's ``event_duration_minutes`` means the task has *no* estimate"
    (because push defaults the slot size when a task has none). Shared by the
    inbound mapper, the merge, and the merge-baseline snapshot so the three can
    never disagree on when a duration becomes an estimate.

    Args:
        minutes: The raw timed-event duration (from
            :func:`~doxtr_doto.calsync.model.timed_duration_minutes`), or None.
        cal: Calendar config supplying the default; when None, any duration is
            taken literally (no default collapse).

    Returns:
        The estimate minutes, or None for "no estimate" (missing duration or a
        duration equal to the default).
    """
    if minutes is None:
        return None
    if cal is not None and minutes == int(cal.event_duration_minutes):
        return None
    return minutes


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
                base_title, base_body, base_due, base_estimate = _base_snapshot_from_event(
                    item.event, cal
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
                        inbound_hash=inbound_hash_of_pushed(item.event),
                        base_title=base_title,
                        base_body=base_body,
                        base_due=base_due,
                        base_estimate=base_estimate,
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
                base_title, base_body, base_due, base_estimate = _base_snapshot_from_event(
                    item.event, cal
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
                        inbound_hash=inbound_hash_of_pushed(item.event),
                        base_title=base_title,
                        base_body=base_body,
                        base_due=base_due,
                        base_estimate=base_estimate,
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


# ===========================================================================
# Pull (calendar -> doto)
# ===========================================================================


class PullAction(str, Enum):
    """A planned inbound action over the local task store."""

    #: Create a new local task from a brand-new user-created remote event.
    IMPORT = "import"
    #: Update an imported local task from a changed remote event.
    UPDATE_LOCAL = "update_local"
    #: Archive the local task for a remote event the user deleted.
    ARCHIVE_LOCAL = "archive_local"
    #: Nothing to do (unchanged, or a doto-owned item pull ignores).
    SKIP = "skip"


class TaskStore(Protocol):
    """Minimal local task-store surface the pull applier needs.

    Satisfied by :class:`doxtr_doto.sync.json_store.JsonTaskStore`; declared as
    a Protocol so the engine stays decoupled from the store implementation and
    is easy to fake in tests.
    """

    def generate_id(self, prefix: str = ...) -> str: ...

    def add_task(self, task_id: str, task_data: dict[str, Any]) -> None: ...

    def get_task(self, task_id: str) -> Any: ...

    def update_task(self, task_id: str, data: dict[str, Any]) -> bool: ...


@dataclass
class PullItem:
    """One planned inbound action.

    Attributes:
        action: What will happen locally (import/update/archive/skip).
        remote_uid: The remote item's iCalUID. For an ARCHIVE_LOCAL (or the
            SKIP that drops a stale record) the remote item is already gone
            from the calendar, so this is the UID doto still has tracked for it.
        task_id: The local task id (filled for update/archive; empty for a
            brand-new import until it is applied).
        reason: Short human-readable justification (for dry-run output).
        remote: The source :class:`RemoteEvent` (None for ARCHIVE_LOCAL).
        content_hash: Inbound content hash of ``remote`` (for state tracking).
        drop_record: True when applying this item must delete the tracked
            import record (a stale record whose remote item *and* local task
            are both gone). Set explicitly by :func:`build_pull_plan` so the
            applier does not branch on free-text ``reason``.
    """

    action: PullAction
    remote_uid: str
    task_id: str = ""
    reason: str = ""
    remote: Any = None
    content_hash: str = ""
    drop_record: bool = False


@dataclass
class PullPlan:
    """The full set of planned inbound actions."""

    items: list[PullItem] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return a ``{action: count}`` summary."""
        out = {a.value: 0 for a in PullAction}
        for item in self.items:
            out[item.action.value] += 1
        return out

    def actionable(self) -> list[PullItem]:
        """Return only items that change the local store (not SKIP)."""
        return [i for i in self.items if i.action is not PullAction.SKIP]


@dataclass
class PullReport:
    """Outcome of applying a pull plan."""

    imported: int = 0
    updated: int = 0
    archived: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)  # (remote_uid, message)

    def total_changes(self) -> int:
        return self.imported + self.updated + self.archived


def _strip_back_reference(description: str) -> str:
    """Remove a trailing ``[doto:...]`` back-reference marker from a body.

    Push appends ``[doto:<ref>]`` as the last paragraph of the description so a
    calendar item points back at its task. When pulling, we strip that marker
    so a round-tripped body does not accumulate it. Body text is otherwise
    preserved verbatim.

    Robustness: a provider that stores the description as HTML (Google's web UI
    does this) returns the marker separated by ``<br>`` tags rather than
    newlines, and may glue it directly onto the preceding text. We therefore
    normalize ``<br>`` variants to newlines first, then strip a trailing marker
    whether it sits on its own paragraph *or* is appended inline at the very
    end -- so the marker never leaks into an imported/merged body.
    """
    import re

    text = description or ""
    if not text.strip():
        return ""
    # Normalize HTML line breaks (``<br>`` / ``<br/>`` / ``<br />``, any case)
    # to newlines so a marker appended via HTML is treated like a paragraph.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    # Remove a trailing ``[doto:...]`` token (optionally preceded by blank
    # lines/whitespace), whether on its own line or glued to the end.
    text = re.sub(r"\s*\[doto:[^\]]*\]\s*$", "", text)

    # Fallback for any remaining whole-line marker paragraphs (defensive;
    # preserves the original line-based behavior).
    lines = text.rstrip().split("\n")
    while (
        lines
        and lines[-1].strip().startswith(BACK_REFERENCE_OPEN)
        and lines[-1].strip().endswith(BACK_REFERENCE_CLOSE)
    ):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines).rstrip()


def build_pull_plan(
    remote_events: list[RemoteEvent],
    tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
) -> PullPlan:
    """Compute the inbound (calendar -> doto) plan.

    Args:
        remote_events: The provider's current view of the calendar.
        tasks: Mapping of task_id -> task data (used to know which imported
            tasks still exist locally).
        state: Loaded sync state (tracks previously imported remote items).
        cal: Resolved calendar config (provides the provider/calendar
            namespace keys).

    Returns:
        A :class:`PullPlan`.
    """
    provider = cal.provider
    calendar = cal.calendar
    plan = PullPlan()

    seen_uids: set[str] = set()
    for remote in remote_events:
        uid = remote.uid or ""
        if uid:
            seen_uids.add(uid)

        # doto-owned items round-trip through push; pull never imports them.
        if is_doto_uid(uid):
            plan.items.append(
                PullItem(
                    action=PullAction.SKIP,
                    remote_uid=uid,
                    task_id=task_id_from_uid(uid) or "",
                    reason="doto-owned (handled by push)",
                    remote=remote,
                )
            )
            continue

        new_hash = remote_content_hash(remote)
        prior = state.get_imported(provider, calendar, uid) if uid else None

        if prior is None:
            # Brand-new user-created event -> import as a task.
            plan.items.append(
                PullItem(
                    action=PullAction.IMPORT,
                    remote_uid=uid,
                    reason="new remote event",
                    remote=remote,
                    content_hash=new_hash,
                )
            )
            continue

        # Previously imported. Did it change, and does its task still exist?
        local_exists = prior.task_id in tasks
        if not local_exists:
            # The local task was deleted; don't recreate it (push handles the
            # remote side if it was doto-owned, which it is not here). Treat as
            # a no-op and leave the import record so we don't re-import.
            plan.items.append(
                PullItem(
                    action=PullAction.SKIP,
                    remote_uid=uid,
                    task_id=prior.task_id,
                    reason="local task gone; not re-importing",
                    remote=remote,
                    content_hash=new_hash,
                )
            )
            continue

        if prior.content_hash != new_hash:
            plan.items.append(
                PullItem(
                    action=PullAction.UPDATE_LOCAL,
                    remote_uid=uid,
                    task_id=prior.task_id,
                    reason="remote event changed",
                    remote=remote,
                    content_hash=new_hash,
                )
            )
        else:
            plan.items.append(
                PullItem(
                    action=PullAction.SKIP,
                    remote_uid=uid,
                    task_id=prior.task_id,
                    reason="unchanged",
                    remote=remote,
                    content_hash=new_hash,
                )
            )

    # Previously-imported remote items that have vanished from the calendar:
    # the user deleted them remotely -> archive the local task (soft delete).
    for uid in state.imported_uids(provider, calendar):
        if uid in seen_uids:
            continue
        prior = state.get_imported(provider, calendar, uid)
        if prior is None:
            continue
        if prior.task_id in tasks:
            plan.items.append(
                PullItem(
                    action=PullAction.ARCHIVE_LOCAL,
                    remote_uid=uid,
                    task_id=prior.task_id,
                    reason="remote event deleted by user",
                )
            )
        else:
            # Local task already gone too; just drop the stale import record.
            plan.items.append(
                PullItem(
                    action=PullAction.SKIP,
                    remote_uid=uid,
                    task_id=prior.task_id,
                    reason="remote and local both gone; dropping record",
                    drop_record=True,
                )
            )

    return plan


def _task_fields_from_remote(remote: RemoteEvent, cal: CalendarConfig) -> dict[str, Any]:
    """Built-in RemoteEvent -> task-fields mapping (summary/body/due/estimate).

    This is the default :data:`InboundMapper`. A downstream can replace it via
    :func:`register_inbound_mapper` to customize how a pulled calendar item maps
    onto a doto task (extra fields, tag handling, body formatting, ...) without
    editing core, mirroring :func:`~doxtr_doto.calsync.model.register_projector`
    on the outbound side.

    Estimate: a **timed** event encodes a duration (``end - start``) that push
    derived from the task's ``estimate`` (or the calendar default
    ``event_duration_minutes`` when the task had none). We map that duration
    back onto ``estimate`` so a user who resized the event on the calendar
    (e.g. 10:45-11:30 -> 45m) sees the task's expected duration update and the
    end time recompute on the next push. To avoid stamping a *spurious*
    estimate on an event that merely has the default slot size (a task pushed
    with no estimate round-trips as a default-length event), the estimate is
    only set when the event's duration differs from ``event_duration_minutes``.
    """
    from doxtr_doto.date_utils import format_duration_minutes

    fields: dict[str, Any] = {
        "title": remote.summary or "(untitled)",
        "body": _strip_back_reference(remote.description),
    }
    due = remote.inbound_due()
    if due is not None:
        fields["due"] = due
    minutes = _non_default_estimate_minutes(remote.inbound_estimate_minutes(), cal)
    if minutes is not None:
        fields["estimate"] = format_duration_minutes(minutes)
    return fields


# ---------------------------------------------------------------------------
# Inbound-mapping extension point
# ---------------------------------------------------------------------------
#: Signature of a RemoteEvent -> task-fields mapper: ``(remote, cal)``.
InboundMapper = Callable[["RemoteEvent", "CalendarConfig"], dict[str, Any]]

#: The active inbound mapper. Defaults to the built-in
#: :func:`_task_fields_from_remote`; swap it via :func:`register_inbound_mapper`
#: to customize the calendar-item -> task mapping independently of any provider,
#: mirroring :func:`~doxtr_doto.calsync.model.register_projector` on push.
_INBOUND_MAPPER: InboundMapper = _task_fields_from_remote


def register_inbound_mapper(fn: InboundMapper) -> None:
    """Replace the RemoteEvent -> task-fields mapping used by pull.

    Downstream extension point (the pull-side counterpart to
    :func:`~doxtr_doto.calsync.model.register_projector`): a child project can
    customize how an imported calendar item maps onto a task -- extra fields,
    category/tag handling, body formatting -- without editing core and without
    touching any provider/transport code.

    Args:
        fn: The replacement mapper. It must accept ``(remote, cal)`` and return
            a dict of task fields (at least ``title``; ``body``/``due`` are
            optional).
    """
    global _INBOUND_MAPPER
    _INBOUND_MAPPER = fn


def inbound_map(remote: RemoteEvent, cal: CalendarConfig) -> dict[str, Any]:
    """Map a remote event to task fields via the active inbound mapper.

    This is the entry point the pull applier calls; it delegates to the
    built-in :func:`_task_fields_from_remote` unless a downstream has registered
    its own via :func:`register_inbound_mapper`.
    """
    return _INBOUND_MAPPER(remote, cal)


def apply_pull_plan(
    plan: PullPlan,
    store: TaskStore,
    state: CalSyncState,
    cal: CalendarConfig,
    *,
    id_prefix: str = "DOTO",
) -> PullReport:
    """Apply an inbound ``plan`` to the local ``store``, updating ``state``.

    Each item is applied independently; a failure on one item is recorded and
    does not abort the rest. State is mutated in-memory; callers are
    responsible for calling ``state.save()`` and persisting the store.

    Args:
        plan: The plan from :func:`build_pull_plan`.
        store: The local task store (see :class:`TaskStore`).
        state: Sync state to update (imported-item tracking).
        cal: Calendar config (provider/calendar namespace keys).
        id_prefix: Prefix for generated task ids (defaults to ``"DOTO"``).

    Returns:
        A :class:`PullReport`.
    """
    report = PullReport()
    now = datetime.now().isoformat()
    pname = cal.provider
    cname = cal.calendar

    for item in plan.items:
        try:
            if item.action is PullAction.SKIP:
                report.skipped += 1
                # Reconcile a stale record whose local task is also gone.
                if item.drop_record:
                    state.delete_imported(pname, cname, item.remote_uid)
                continue

            if item.action is PullAction.IMPORT:
                task_id = store.generate_id(id_prefix)
                data = inbound_map(item.remote, cal)
                data.setdefault("status", "open")
                data["created"] = now
                data["updated"] = now
                store.add_task(task_id, data)
                state.set_imported(
                    pname,
                    cname,
                    item.remote_uid,
                    ImportedRef(
                        task_id=task_id,
                        content_hash=item.content_hash,
                        remote_id=getattr(item.remote, "remote_id", "") or "",
                        etag=getattr(item.remote, "etag", "") or "",
                        updated=now,
                    ),
                )
                report.imported += 1

            elif item.action is PullAction.UPDATE_LOCAL:
                data = inbound_map(item.remote, cal)
                data["updated"] = now
                store.update_task(item.task_id, data)
                prior = state.get_imported(pname, cname, item.remote_uid)
                state.set_imported(
                    pname,
                    cname,
                    item.remote_uid,
                    ImportedRef(
                        task_id=item.task_id,
                        content_hash=item.content_hash,
                        remote_id=getattr(item.remote, "remote_id", "") or "",
                        etag=getattr(item.remote, "etag", "") or (prior.etag if prior else ""),
                        updated=now,
                    ),
                )
                report.updated += 1

            elif item.action is PullAction.ARCHIVE_LOCAL:
                store.update_task(
                    item.task_id,
                    {"archived": True, "archived_on": now, "updated": now},
                )
                state.delete_imported(pname, cname, item.remote_uid)
                report.archived += 1
        except Exception as exc:  # per-item recoverable
            report.errors.append((item.remote_uid or item.task_id, str(exc)))

    return report


# ===========================================================================
# Two-way orchestration
# ===========================================================================


class ConflictResolution(str, Enum):
    """How a dual local+remote edit of a doto-owned item is resolved."""

    #: Keep the local task; push overwrites the remote (the default, and the
    #: only behavior wired into the current orchestration).
    LOCAL_WINS = "local-wins"
    #: Reserved for downstreams that import the remote edit over the local one.
    REMOTE_WINS = "remote-wins"
    #: Reserved for downstreams that pick the most recently modified side.
    NEWEST_WINS = "newest-wins"
    #: Three-way merge the local and remote edits (git-style, line-level on the
    #: body with conflict markers on a true divergence); the merged result is
    #: written locally and re-pushed so both sides converge. Wired into
    #: :func:`two_way_sync`.
    MERGE = "merge"


#: Signature of a conflict policy: given the conflicted ``task_id``, the local
#: ``task`` data, the current ``remote`` doto-owned event, and the stored
#: ``prior`` ref, return the :class:`ConflictResolution` to apply.
ConflictPolicy = Callable[
    [str, dict[str, Any], "RemoteEvent | None", "RemoteRef"], ConflictResolution
]


def local_wins_policy(
    task_id: str,
    task: dict[str, Any],
    remote: RemoteEvent | None,
    prior: RemoteRef,
) -> ConflictResolution:
    """Default conflict policy: the local task always wins.

    doto is the system of record for the items it owns, so a dual edit is
    resolved in favor of the local task and the subsequent push overwrites the
    remote. This never loses local work. A downstream wanting remote-wins or
    newest-wins passes its own callable to :func:`two_way_sync` instead.
    """
    return ConflictResolution.LOCAL_WINS


def merge_wins_policy(
    task_id: str,
    task: dict[str, Any],
    remote: RemoteEvent | None,
    prior: RemoteRef,
) -> ConflictResolution:
    """Conflict policy that three-way **merges** local and remote edits.

    When both a local task and its doto-owned remote event changed since the
    last sync, merge the two field-by-field (git-style, line-level on the
    multi-line ``body``) instead of discarding either side. See
    :func:`merge_doto_owned_conflict` for the field rules. Pass this to
    :func:`two_way_sync` (``conflict_policy=merge_wins_policy``) to enable it.
    """
    return ConflictResolution.MERGE


# ---------------------------------------------------------------------------
# Body-merge extension point
# ---------------------------------------------------------------------------
#: Signature of a three-way body merger: ``(base, local, remote) -> MergeOutcome``.
BodyMerger = Callable[[str, str, str], "MergeOutcome"]


def _default_body_merger(base: str, local: str, remote: str) -> MergeOutcome:
    """Default body merger: the git-style diff3 line merge."""
    from doxtr_doto.calsync.textmerge import merge_three_way

    return merge_three_way(base, local, remote)


#: The active three-way body merger. Defaults to the diff3 line-level merge;
#: swap it via :func:`register_body_merger` to customize how a doto-owned
#: item's multi-line body is reconciled on a two-way merge (e.g. a
#: semantic/structure-aware or HTML-aware merge) without editing core --
#: mirroring :func:`register_inbound_mapper` and
#: :func:`~doxtr_doto.calsync.model.register_projector`.
_BODY_MERGER: BodyMerger = _default_body_merger


def register_body_merger(fn: BodyMerger) -> None:
    """Replace the three-way body-merge strategy used by the merge policy.

    Downstream extension point (the body-merge counterpart to
    :func:`register_inbound_mapper`): a child project can swap the line-level
    diff3 merge for its own strategy without editing
    :func:`merge_doto_owned_conflict` or any provider code.

    Args:
        fn: The replacement merger. It must accept ``(base, local, remote)``
            and return a :class:`~doxtr_doto.calsync.textmerge.MergeOutcome`
            (merged text + a conflict flag).
    """
    global _BODY_MERGER
    _BODY_MERGER = fn


@dataclass
class FieldConflict:
    """The three candidate values for one field that diverged on both sides.

    Captured so a resolution UI/CLI can offer a clean "keep local / keep remote
    / keep both" choice instead of only surfacing git-style markers. ``both``
    is the diff3-merged text (with markers) for ``body`` and a joined value for
    scalars; it is what is written into the task until the user resolves it.

    Attributes:
        field: The task field name (``title`` / ``body`` / ``due`` /
            ``estimate``).
        base: The last-synced common-ancestor value.
        local: The current local value.
        remote: The current remote value.
        both: The "keep both" value (diff3 markers for the body; a joined
            string for scalars).
    """

    field: str
    base: str
    local: str
    remote: str
    both: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "base": self.base,
            "local": self.local,
            "remote": self.remote,
            "both": self.both,
        }


@dataclass
class MergedFields:
    """Result of three-way merging one conflicted doto-owned task.

    Attributes:
        fields: The merged ``{title, body, due}`` task fields to write locally
            (and then re-push so the calendar converges).
        had_text_conflict: True when a field diverged on both sides and the
            merged value carries git-style conflict markers the user must
            resolve by hand.
        conflicts: Per-field :class:`FieldConflict` records for every field
            that diverged on both sides, carrying the base/local/remote/both
            candidates so a resolution step can offer a simple choice. Empty
            when the merge was clean.
    """

    fields: dict[str, Any]
    had_text_conflict: bool
    conflicts: list[FieldConflict] = field(default_factory=list)


def merge_doto_owned_conflict(
    task: dict[str, Any],
    remote: RemoteEvent,
    prior: RemoteRef,
    cal: CalendarConfig | None = None,
) -> MergedFields:
    """Three-way merge a doto-owned event edited on both sides.

    The common ancestor is the last-synced snapshot stored on ``prior``
    (``base_title`` / ``base_body`` / ``base_due`` / ``base_estimate``). For
    each mergeable field:

    * **title**, **due** and **estimate** are scalars: if only one side
      changed, take it; if both changed identically, take that; if both changed
      differently, keep the local value and flag a conflict (a scalar can't be
      line-merged -- the divergence is surfaced in the report, local is
      retained so nothing is silently dropped).
    * **body** is multi-line text: a line-level three-way merge
      (:func:`~doxtr_doto.calsync.textmerge.merge_three_way`) combines
      non-overlapping edits from both sides and emits git-style conflict
      markers only on a genuinely divergent hunk.

    The **estimate** merge lets a user who *resized* a timed event on the
    calendar (changing its end time) have the new duration flow back onto the
    task's ``estimate`` so the end time recomputes on the next push. Estimate
    values are compared by their parsed minute count (so ``"60m"`` and ``"1h"``
    are equal) and written in the canonical compact form.

    Args:
        task: The current local task (``title`` / ``body`` / ``due`` /
            ``estimate``).
        remote: The live remote event (its inbound-mapped title/body/due and
            timed-event duration).
        prior: The sync ref carrying the last-synced base snapshot.
        cal: Optional calendar config; when given, a remote duration equal to
            ``event_duration_minutes`` is treated as "no estimate" (mirrors the
            inbound mapper). When None, any remote duration is taken literally.

    Returns:
        A :class:`MergedFields` with the merged fields and a conflict flag.
    """
    from doxtr_doto.date_utils import format_duration_minutes, parse_duration_safe

    local_title = str(task.get("title") or "")
    local_body = str(task.get("body") or "")
    local_due = str(task.get("due") or "")

    remote_title = remote.summary or ""
    remote_body = _strip_back_reference(remote.description or "")
    remote_due = remote.inbound_due() or ""

    base_title = prior.base_title
    base_body = prior.base_body
    base_due = prior.base_due

    had_conflict = False
    fields: dict[str, Any] = {}
    conflicts: list[FieldConflict] = []

    merged_title, t_conflict = _merge_scalar(base_title, local_title, remote_title)
    fields["title"] = merged_title
    had_conflict = had_conflict or t_conflict
    if t_conflict:
        conflicts.append(
            FieldConflict(
                field="title",
                base=base_title,
                local=local_title,
                remote=remote_title,
                both=_join_scalar_both(local_title, remote_title),
            )
        )

    body_outcome = _BODY_MERGER(base_body, local_body, remote_body)
    fields["body"] = body_outcome.text
    had_conflict = had_conflict or body_outcome.conflicted
    if body_outcome.conflicted:
        conflicts.append(
            FieldConflict(
                field="body",
                base=base_body,
                local=local_body,
                remote=remote_body,
                both=body_outcome.text,
            )
        )

    merged_due, d_conflict = _merge_scalar(base_due, local_due, remote_due)
    # A due must stay a valid scalar; never write a marker string into it. On a
    # true due divergence keep local and let the flag surface the conflict.
    fields["due"] = local_due if d_conflict else merged_due
    had_conflict = had_conflict or d_conflict
    if d_conflict:
        # A due has no sensible "both" value (it must stay a valid scalar), so
        # the "both" candidate falls back to local -- the resolver still offers
        # local vs remote.
        conflicts.append(
            FieldConflict(
                field="due",
                base=base_due,
                local=local_due,
                remote=remote_due,
                both=local_due,
            )
        )

    # Estimate: merge by parsed minutes so "60m" and "1h" compare equal, then
    # emit the canonical compact form. A remote timed event always carries a
    # duration; map it onto the task's estimate so a calendar resize round-
    # trips. A duration equal to the calendar default is treated as "no
    # estimate" (empty), mirroring the inbound mapper, so a default-length
    # event does not stamp a spurious estimate. On a true divergence keep local
    # (scalar, no marker possible).
    local_est = str(parse_duration_safe(task.get("estimate")) or "")
    remote_minutes = _non_default_estimate_minutes(remote.inbound_estimate_minutes(), cal)
    remote_est = str(remote_minutes) if remote_minutes is not None else ""
    base_est = str(parse_duration_safe(prior.base_estimate) or "")
    merged_est, e_conflict = _merge_scalar(base_est, local_est, remote_est)
    chosen_est = local_est if e_conflict else merged_est
    if chosen_est:
        fields["estimate"] = format_duration_minutes(int(chosen_est))
    had_conflict = had_conflict or e_conflict
    if e_conflict:
        local_est_str = format_duration_minutes(int(local_est)) if local_est else ""
        remote_est_str = format_duration_minutes(int(remote_est)) if remote_est else ""
        base_est_str = format_duration_minutes(int(base_est)) if base_est else ""
        conflicts.append(
            FieldConflict(
                field="estimate",
                base=base_est_str,
                local=local_est_str,
                remote=remote_est_str,
                both=local_est_str,
            )
        )

    return MergedFields(fields=fields, had_text_conflict=had_conflict, conflicts=conflicts)


def _join_scalar_both(local: str, remote: str) -> str:
    """\"Keep both\" value for a conflicted scalar: the two values joined.

    A scalar (e.g. a title) cannot carry diff3 markers, so "keep both" simply
    concatenates the two sides with a separator so no text is lost; the user
    can then trim it in the editor. Identical sides collapse to one.
    """
    if local == remote:
        return local
    if not local:
        return remote
    if not remote:
        return local
    return f"{local} / {remote}"


def _merge_scalar(base: str, local: str, remote: str) -> tuple[str, bool]:
    """Three-way merge a scalar string; return ``(value, is_conflict)``.

    Only-one-side-changed takes that side; identical changes collapse; a true
    divergence returns the local value with ``is_conflict=True`` (the caller
    decides how to surface it).
    """
    if local == remote:
        return local, False
    if local == base:
        return remote, False
    if remote == base:
        return local, False
    return local, True


@dataclass
class TwoWayReport:
    """Combined outcome of a two-way (pull + push) sync.

    Attributes:
        pull: The inbound :class:`PullReport`.
        push: The outbound :class:`SyncReport`.
        conflicts: Task ids where both the local task and its doto-owned remote
            event changed since the last sync. Under the default local-wins
            policy these are resolved by the push overwriting the remote; under
            the merge policy they are three-way merged (see ``merged`` /
            ``merge_conflicts``). Surfaced so callers can warn the user.
        merged: Task ids whose dual edit was three-way **merged** (merge policy
            only). A subset of ``conflicts``.
        merge_conflicts: Task ids whose merge produced git-style conflict
            markers the user must resolve by hand (a field diverged on both
            sides). A subset of ``merged``.
    """

    pull: PullReport
    push: SyncReport
    conflicts: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    merge_conflicts: list[str] = field(default_factory=list)


def detect_conflicts(
    remote_events: list[RemoteEvent],
    tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
    *,
    repo_name: str = "",
) -> list[str]:
    """Return task ids with a simultaneous local *and* remote edit.

    A conflict exists for a doto-owned item when BOTH:

    * the task's freshly projected event hash differs from the stored hash
      (the local task changed), and
    * the remote doto-owned event's content differs from the stored hash
      (the remote item changed).

    Per the module's documented policy these are resolved **local-wins**: the
    push pass overwrites the remote. This function only *detects* them so the
    orchestration can report them.
    """
    provider = cal.provider
    calendar = cal.calendar

    # Map doto-owned remote UIDs to their current remote hash.
    remote_hash_by_uid: dict[str, str] = {}
    for remote in remote_events:
        if is_doto_uid(remote.uid):
            remote_hash_by_uid[remote.uid] = remote_content_hash(remote)

    conflicts: list[str] = []
    for task_id, task in tasks.items():
        prior = state.get(provider, calendar, task_id)
        if prior is None:
            continue
        if not _is_schedulable(task, _DEFAULT_EXCLUDE_STATUSES):
            continue
        ref = f"{repo_name}#{task_id}" if repo_name else task_id
        try:
            event = project(task_id, task, cal, back_reference=ref)
        except ValueError:
            continue
        local_changed = content_hash(event) != prior.content_hash
        remote_hash = remote_hash_by_uid.get(prior.uid)
        # Compare the remote item's inbound hash against the inbound baseline we
        # stored at push time, so an untouched remote compares equal (no
        # spurious conflict). A missing baseline (state written before inbound
        # tracking) falls back to the conservative conflict-detecting behavior.
        remote_changed = remote_hash is not None and remote_hash != _pushed_inbound_hash(prior)
        if local_changed and remote_changed:
            conflicts.append(task_id)
    return conflicts


def detect_remote_changed(
    remote_events: list[RemoteEvent],
    tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
) -> list[str]:
    """Return doto-owned task ids whose *remote* event changed since last sync.

    Unlike :func:`detect_conflicts` (which requires a *simultaneous* local and
    remote edit), this flags a doto-owned item whenever the live remote content
    differs from the stored inbound baseline -- regardless of whether the local
    task also changed. The merge policy uses this so a **remote-only** edit of a
    doto event (e.g. a note typed into the calendar app) is still reconciled
    back into the task; a pure three-way merge with an unchanged local side
    simply takes the remote value, so the same code path handles both the
    remote-only and dual-edit cases.

    Tasks with no stored push ref (never pushed) are ignored -- those are not
    doto-owned round-trips. A missing inbound baseline (pre-upgrade state) makes
    any present remote hash count as changed, matching the conservative
    behaviour of :func:`detect_conflicts`.
    """
    provider = cal.provider
    calendar = cal.calendar
    remote_hash_by_uid: dict[str, str] = {}
    for remote in remote_events:
        if is_doto_uid(remote.uid):
            remote_hash_by_uid[remote.uid] = remote_content_hash(remote)

    changed: list[str] = []
    for task_id in tasks:
        prior = state.get(provider, calendar, task_id)
        if prior is None:
            continue
        remote_hash = remote_hash_by_uid.get(prior.uid)
        if remote_hash is not None and remote_hash != _pushed_inbound_hash(prior):
            changed.append(task_id)
    return changed


def _pushed_inbound_hash(prior: RemoteRef) -> str:
    """Inbound-hash baseline for a doto-owned pushed item.

    :func:`apply_plan` stores an inbound-equivalent hash of each pushed event
    (:func:`~doxtr_doto.calsync.ical.inbound_hash_of_pushed`) in
    ``RemoteRef.inbound_hash``. Comparing a live remote inbound hash against
    this baseline means an *untouched* remote compares equal and is not flagged
    as a conflict -- fixing the spurious-conflict-on-every-local-edit bug.

    For state written before inbound tracking existed (``inbound_hash == ""``)
    we keep the old conservative behavior: an empty baseline makes any present
    remote hash count as "changed", so a possible conflict is flagged (resolved
    local-wins, losing nothing) rather than missed. A fresh push repopulates
    the baseline, so this only affects the first sync after upgrading.
    """
    return prior.inbound_hash


def plan_two_way(
    remote_events: list[RemoteEvent],
    pull_tasks: dict[str, dict[str, Any]],
    push_tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
    *,
    repo_name: str = "",
    exclude_statuses: set[str] | None = None,
) -> tuple[PullPlan, SyncPlan, list[str], list[str]]:
    """Compute the pull plan, push plan, conflicts, and remote-only merges.

    Shared by :func:`two_way_sync` (apply) and the CLI two-way ``--dry-run``
    (preview) so the two can never drift. Conflicts are detected against
    ``push_tasks`` -- the same task view the push plan is built from -- so the
    dry-run preview and the applied run report the identical conflict set
    (reconciling the previous active-vs-all-tasks divergence).

    ``remote_only_merges`` are doto-owned tasks whose *remote* changed while the
    local task did not. Under ``conflict_policy = "merge"`` these are reconciled
    on apply (the remote edit flows back) even though they are not conflicts and
    are invisible to the pull/push plans (pull skips doto-owned items; push sees
    an unchanged local hash). Returning them lets the dry-run preview surface
    the merge blast radius instead of showing "nothing to do".

    Args:
        remote_events: The provider's current calendar view.
        pull_tasks: Task view for the inbound plan (typically *all* tasks, so
            an imported task whose local copy was archived is still recognized).
        push_tasks: Task view for the outbound plan and conflict detection
            (typically the *active* tasks that push considers).
        state: Loaded sync state.
        cal: Resolved calendar config.
        repo_name: Repo name for the push back-reference label.
        exclude_statuses: Statuses to keep off the calendar on push.

    Returns:
        ``(pull_plan, push_plan, conflicts, remote_only_merges)``.
    """
    conflicts = detect_conflicts(remote_events, push_tasks, state, cal, repo_name=repo_name)
    # Remote-only changes to doto-owned items (the merge policy reconciles these
    # on apply; exclude the true conflicts, which are reported separately).
    remote_changed = detect_remote_changed(remote_events, push_tasks, state, cal)
    _conflict_set = set(conflicts)
    remote_only_merges = [tid for tid in remote_changed if tid not in _conflict_set]
    pull_plan = build_pull_plan(remote_events, pull_tasks, state, cal)
    # Tasks that originate from the calendar (imported by pull) must not be
    # pushed back up as doto-owned events -- that would duplicate the user's
    # item. Exclude them from the push plan.
    imported_ids = state.imported_task_ids(cal.provider, cal.calendar)
    push_plan = build_plan(
        push_tasks,
        state,
        cal,
        repo_name=repo_name,
        exclude_statuses=exclude_statuses,
        skip_task_ids=imported_ids,
    )
    return pull_plan, push_plan, conflicts, remote_only_merges


def two_way_sync(
    provider: CalendarProvider,
    store: TaskStore,
    tasks: dict[str, dict[str, Any]],
    state: CalSyncState,
    cal: CalendarConfig,
    *,
    repo_name: str = "",
    exclude_statuses: set[str] | None = None,
    id_prefix: str = "DOTO",
    reload_tasks: Any = None,
    conflict_policy: ConflictPolicy = local_wins_policy,
) -> TwoWayReport:
    """Run a two-way sync: pull (calendar -> doto) then push (doto -> calendar).

    Ordering and conflict policy are documented in the module docstring: pull
    first (so imports exist before push plans), local-wins on a dual edit.

    The ``conflict_policy`` seam mirrors
    :func:`~doxtr_doto.calsync.model.register_projector` and
    :func:`register_inbound_mapper`: it is an injectable callable (defaulting to
    :func:`local_wins_policy`) so a downstream can choose a different resolution
    without editing ``two_way_sync``. Two resolutions are wired into the
    built-in orchestration:

    * :data:`ConflictResolution.LOCAL_WINS` (default) -- pull skips the
      doto-owned item and the subsequent push overwrites the remote with the
      local state (the remote edit is discarded).
    * :data:`ConflictResolution.MERGE` (:func:`merge_wins_policy`) -- the local
      and remote edits are three-way merged (git-style, line-level on the
      ``body``); the merged fields are written to the local store **before**
      push plans, so push re-pushes the merged result and both sides converge.
      A field that diverged on both sides is written with git-style conflict
      markers and reported in ``merge_conflicts``.

    Any other resolution a custom policy returns currently falls back to the
    local-wins flow (it only changes what is reported), keeping existing
    behavior stable.

    Args:
        provider: A connected provider (must implement ``list_events``).
        store: The local task store (for imports/updates/archives).
        tasks: Current task mapping; used for pull planning and (after reload)
            push planning.
        state: Loaded sync state.
        cal: Resolved calendar config.
        repo_name: Repo name for the push back-reference label.
        exclude_statuses: Statuses to keep off the calendar on push.
        id_prefix: Prefix for generated task ids on import.
        reload_tasks: Optional zero-arg callable returning a fresh task mapping
            after the pull pass has mutated the store (so push sees imported
            tasks). When None, the in-memory ``tasks`` is reused as-is -- the
            caller is then responsible for keeping it current.
        conflict_policy: Resolution policy for a dual local+remote edit
            (defaults to :func:`local_wins_policy`; pass
            :func:`merge_wins_policy` for three-way merge).

    Returns:
        A :class:`TwoWayReport`.
    """
    remote_events = provider.list_events()

    # Build the remote doto-owned lookup once so the policy callable gets the
    # live remote event for each conflicted task.
    remote_by_uid: dict[str, RemoteEvent] = {r.uid: r for r in remote_events if is_doto_uid(r.uid)}

    conflicts = detect_conflicts(remote_events, tasks, state, cal, repo_name=repo_name)
    # Consult the policy and apply the chosen resolution.
    #
    # LOCAL_WINS keeps the built-in pull-skip / push-overwrite flow: a dual edit
    # is reported, the local task is retained, and push overwrites the remote.
    #
    # MERGE three-way merges the local and remote edits and writes the result
    # to the store *now*, before pull/push plan -- so the reloaded push view
    # picks up the merged fields and re-pushes them, converging the calendar.
    # Writing merged fields changes the task's projected hash, so build_plan
    # naturally plans an UPDATE for it; no manual state invalidation is needed.
    #
    # The merge policy must also catch a **remote-only** edit of a doto-owned
    # event (the local task unchanged): pull skips doto-owned items entirely,
    # so without this the remote edit would never come back. We therefore apply
    # the merge to the union of true conflicts and remote-changed doto tasks.
    # A three-way merge with an unchanged local side simply takes the remote
    # value, so the same path handles remote-only and dual edits identically.
    merged_ids: list[str] = []
    merge_conflict_ids: list[str] = []

    # Decide the resolution from the detected conflicts (policy is consulted per
    # task; in practice it returns a constant). When there is no true conflict
    # we still consult it with the first remote-changed task so a merge policy
    # engages on a remote-only edit.
    remote_changed_ids = detect_remote_changed(remote_events, tasks, state, cal)
    probe_ids = conflicts or remote_changed_ids
    use_merge = False
    for task_id in probe_ids:
        prior = state.get(cal.provider, cal.calendar, task_id)
        if prior is None:
            continue
        resolution = conflict_policy(
            task_id, tasks.get(task_id, {}), remote_by_uid.get(prior.uid), prior
        )
        if resolution is ConflictResolution.MERGE:
            use_merge = True
        break

    if use_merge:
        # Merge every doto-owned task whose remote changed (this set already
        # includes the true conflicts, since a dual edit also changed remote).
        now = datetime.now().isoformat()
        for task_id in remote_changed_ids:
            prior = state.get(cal.provider, cal.calendar, task_id)
            if prior is None:
                continue
            remote = remote_by_uid.get(prior.uid)
            if remote is None:
                continue
            result = merge_doto_owned_conflict(tasks.get(task_id, {}), remote, prior, cal)
            # Persist a ``sync_conflict`` flag so a task whose body was written
            # with git-style conflict markers can be found later (``doto list
            # --conflicts`` / the TUI filter) without re-running a sync. It is
            # explicitly cleared (set False) on a clean merge so resolving the
            # markers and re-syncing drops the flag. Alongside the flag we stash
            # the per-field base/local/remote/both candidates under
            # ``_sync.conflict`` so a resolver (``doto calsync resolve`` / the
            # TUI ``c`` dialog) can offer a simple keep-local/remote/both choice
            # without re-running a sync. A clean merge clears the stash.
            conflict_fields: dict[str, Any] = {"sync_conflict": bool(result.had_text_conflict)}
            if result.had_text_conflict:
                conflict_payload = {
                    "detected": now,
                    "fields": [c.to_dict() for c in result.conflicts],
                }
            else:
                conflict_payload = None
            store.update_task(
                task_id,
                {
                    **result.fields,
                    **conflict_fields,
                    "_sync": {"conflict": conflict_payload},
                    "updated": now,
                },
            )
            # Keep the in-memory view consistent for the (optional) non-reload
            # path so push sees the merged fields even when reload_tasks is None.
            if task_id in tasks:
                merged_sync = {
                    **(tasks[task_id].get("_sync") or {}),
                    "conflict": conflict_payload,
                }
                tasks[task_id] = {
                    **tasks[task_id],
                    **result.fields,
                    **conflict_fields,
                    "_sync": merged_sync,
                    "updated": now,
                }
            merged_ids.append(task_id)
            if result.had_text_conflict:
                merge_conflict_ids.append(task_id)
            # Refresh the inbound baseline to the now-reconciled remote hash so
            # the next sync does not re-detect this as a remote change. Without
            # this, a merge that produced no local change (e.g. an all-day
            # event, or state written by an older hash formula) would never push
            # -- leaving the stale baseline and re-merging on every run. If push
            # does re-push the merged result below, apply_plan overwrites this
            # baseline again with the pushed state (also correct).
            refreshed = RemoteRef(
                uid=prior.uid,
                etag=prior.etag,
                href=prior.href,
                content_hash=prior.content_hash,
                remote_id=prior.remote_id,
                inbound_hash=remote_content_hash(remote),
                base_title=result.fields.get("title", prior.base_title),
                base_body=result.fields.get("body", prior.base_body),
                base_due=result.fields.get("due", prior.base_due),
                base_estimate=result.fields.get("estimate", prior.base_estimate),
                updated=now,
            )
            state.set(cal.provider, cal.calendar, task_id, refreshed)

    pull_plan = build_pull_plan(remote_events, tasks, state, cal)
    pull_report = apply_pull_plan(pull_plan, store, state, cal, id_prefix=id_prefix)

    push_tasks = reload_tasks() if callable(reload_tasks) else tasks
    # Tasks that originate from the calendar (imported by pull) must not be
    # pushed back up as doto-owned events -- that would duplicate the user's
    # item. Exclude them from the push plan.
    imported_ids = state.imported_task_ids(cal.provider, cal.calendar)
    push_plan = build_plan(
        push_tasks,
        state,
        cal,
        repo_name=repo_name,
        exclude_statuses=exclude_statuses,
        skip_task_ids=imported_ids,
    )
    push_report = apply_plan(push_plan, provider, state, cal)

    return TwoWayReport(
        pull=pull_report,
        push=push_report,
        conflicts=conflicts,
        merged=merged_ids,
        merge_conflicts=merge_conflict_ids,
    )
