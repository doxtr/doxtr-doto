"""Persisted calendar-sync state (``.doto/calsync.json``).

Tracks, per task, what doto last pushed to a given calendar: the remote item's
UID, the server ETag (for optimistic concurrency), the remote href (CalDAV
resource URL), and the content hash of the projected event. The engine uses
this to decide whether a task is unchanged (skip), new (create), or modified
(update), and to find the item to delete when a task loses its due date or is
archived.

State is namespaced by ``provider + calendar`` so a single project can sync the
same tasks to multiple calendars without collisions. Writes are atomic
(temp-file + rename), matching :class:`doxtr_doto.sync.json_store.JsonTaskStore`.
"""

from __future__ import annotations

import builtins
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CALSYNC_STATE_VERSION = 1


@dataclass
class RemoteRef:
    """What doto knows about one task's remote calendar item.

    Attributes:
        uid: iCalendar UID of the remote item (doto-assigned).
        etag: Last-seen server ETag, used for conditional updates/deletes.
        href: CalDAV resource URL (empty for API-based providers).
        content_hash: Hash of the projected event last successfully pushed.
        remote_id: Provider-native id (Google/MS event id); empty for CalDAV.
        inbound_hash: Inbound-equivalent hash of the pushed item, i.e. the
            :func:`~doxtr_doto.calsync.ical.remote_content_hash` of a
            ``RemoteEvent`` built from the event doto last pushed. Stored as the
            baseline the two-way conflict detector compares a live remote hash
            against, so an untouched remote compares *equal* (no spurious
            conflict). Defaults to the empty string; state files written before
            two-way conflict detection load it as empty (backward compatible).
        base_title: Last-synced ``title`` value -- the common-ancestor baseline
            for the three-way **merge** conflict policy. Empty on state written
            before merge support (the merge then falls back to a two-way
            reconcile with no ancestor, which still never loses text).
        base_body: Last-synced ``body`` value (merge ancestor for the
            line-level body merge).
        base_due: Last-synced ``due`` value as an ISO string (merge ancestor).
        base_estimate: Last-synced ``estimate`` value as a compact duration
            string (merge ancestor for the scalar estimate merge). Empty when
            the task had no estimate (so the event used the default duration).
        updated: ISO timestamp of the last successful push.
    """

    uid: str
    etag: str = ""
    href: str = ""
    content_hash: str = ""
    remote_id: str = ""
    inbound_hash: str = ""
    base_title: str = ""
    base_body: str = ""
    base_due: str = ""
    base_estimate: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "uid": self.uid,
            "etag": self.etag,
            "href": self.href,
            "content_hash": self.content_hash,
            "remote_id": self.remote_id,
            "inbound_hash": self.inbound_hash,
            "base_title": self.base_title,
            "base_body": self.base_body,
            "base_due": self.base_due,
            "base_estimate": self.base_estimate,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteRef:
        return cls(
            uid=str(data.get("uid", "")),
            etag=str(data.get("etag", "")),
            href=str(data.get("href", "")),
            content_hash=str(data.get("content_hash", "")),
            remote_id=str(data.get("remote_id", "")),
            inbound_hash=str(data.get("inbound_hash", "")),
            base_title=str(data.get("base_title", "")),
            base_body=str(data.get("base_body", "")),
            base_due=str(data.get("base_due", "")),
            base_estimate=str(data.get("base_estimate", "")),
            updated=str(data.get("updated", "")),
        )


@dataclass
class ImportedRef:
    """What doto knows about a remote item it imported into the task store.

    This is the inbound (pull) counterpart to :class:`RemoteRef`: it records
    that a *user-created* remote event (not a doto-owned one) was turned into a
    local task, so a subsequent pull recognizes it instead of re-importing it,
    and a now-missing remote item can be reconciled against its local task.

    Keyed in state by the remote item's iCalUID.

    Attributes:
        task_id: The local doto task id created for this remote item.
        content_hash: Hash of the remote item's salient fields at import time
            (used to detect inbound changes on later pulls).
        remote_id: Provider-native id (empty for CalDAV).
        etag: Last-seen server ETag.
        updated: ISO timestamp of the import / last inbound reconcile.
    """

    task_id: str
    content_hash: str = ""
    remote_id: str = ""
    etag: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "content_hash": self.content_hash,
            "remote_id": self.remote_id,
            "etag": self.etag,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportedRef:
        return cls(
            task_id=str(data.get("task_id", "")),
            content_hash=str(data.get("content_hash", "")),
            remote_id=str(data.get("remote_id", "")),
            etag=str(data.get("etag", "")),
            updated=str(data.get("updated", "")),
        )


def _namespace(provider: str, calendar: str) -> str:
    """Build the state namespace key for a provider+calendar pair."""
    return f"{provider}::{calendar or 'default'}"


class CalSyncState:
    """Load/save calendar-sync state for a project.

    The on-disk shape is::

        {
            "version": 1,
            "updated": "<iso>",
            "namespaces": {
                "google::primary": {
                    # per task: uid, etag, href, content_hash, remote_id,
                    # inbound_hash, and the merge-ancestor snapshot
                    # (base_title/base_body/base_due/base_estimate).
                    "<task_id>": {"uid": ..., "etag": ..., "content_hash": ...},
                    ...
                },
                ...
            },
            "imported": {
                "google::primary": {
                    "<remote_ical_uid>": {"task_id": ..., "content_hash": ...},
                    ...
                },
                ...
            }
        }

    ``namespaces`` tracks what push wrote (keyed by local task id); ``imported``
    tracks what pull brought in (keyed by remote iCalUID). The ``imported`` map
    is optional on disk -- state files written before two-way sync load fine
    and default it to empty, so the state version stays at 1.
    """

    def __init__(self, path: Path) -> None:
        """Initialize against ``path`` (``.doto/calsync.json``)."""
        self.path = path
        self._data: dict[str, Any] | None = None

    def load(self) -> None:
        """Load state from disk, initializing an empty structure if absent."""
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = self._empty()
        else:
            self._data = self._empty()
        # Defensive: ensure required keys exist.
        self._data.setdefault("version", CALSYNC_STATE_VERSION)
        self._data.setdefault("namespaces", {})
        # ``imported`` was added for two-way (pull) sync; older files omit it.
        self._data.setdefault("imported", {})

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": CALSYNC_STATE_VERSION,
            "updated": datetime.now().isoformat(),
            "namespaces": {},
            "imported": {},
        }

    def _ns(self, provider: str, calendar: str) -> dict[str, Any]:
        assert self._data is not None, "call load() first"
        key = _namespace(provider, calendar)
        ns: dict[str, Any] = self._data["namespaces"].setdefault(key, {})
        return ns

    def get(self, provider: str, calendar: str, task_id: str) -> RemoteRef | None:
        """Return the stored :class:`RemoteRef` for a task, or None."""
        raw = self._ns(provider, calendar).get(task_id)
        return RemoteRef.from_dict(raw) if raw else None

    def set(self, provider: str, calendar: str, task_id: str, ref: RemoteRef) -> None:
        """Store/replace the :class:`RemoteRef` for a task."""
        self._ns(provider, calendar)[task_id] = ref.to_dict()

    def delete(self, provider: str, calendar: str, task_id: str) -> None:
        """Remove a task's stored ref (after a successful remote delete)."""
        self._ns(provider, calendar).pop(task_id, None)

    def task_ids(self, provider: str, calendar: str) -> list[str]:
        """Return all task ids with stored state for a provider+calendar."""
        return list(self._ns(provider, calendar).keys())

    # -- Imported (pull) remote items --------------------------------------
    def _imported_ns(self, provider: str, calendar: str) -> dict[str, Any]:
        assert self._data is not None, "call load() first"
        key = _namespace(provider, calendar)
        imported: dict[str, Any] = self._data["imported"].setdefault(key, {})
        return imported

    def get_imported(self, provider: str, calendar: str, remote_uid: str) -> ImportedRef | None:
        """Return the :class:`ImportedRef` for a remote iCalUID, or None."""
        raw = self._imported_ns(provider, calendar).get(remote_uid)
        return ImportedRef.from_dict(raw) if raw else None

    def set_imported(self, provider: str, calendar: str, remote_uid: str, ref: ImportedRef) -> None:
        """Store/replace the :class:`ImportedRef` for a remote iCalUID."""
        self._imported_ns(provider, calendar)[remote_uid] = ref.to_dict()

    def delete_imported(self, provider: str, calendar: str, remote_uid: str) -> None:
        """Remove the imported-item record for a remote iCalUID."""
        self._imported_ns(provider, calendar).pop(remote_uid, None)

    def imported_uids(self, provider: str, calendar: str) -> list[str]:
        """Return all tracked remote iCalUIDs imported for a provider+calendar."""
        return list(self._imported_ns(provider, calendar).keys())

    def imported_task_ids(self, provider: str, calendar: str) -> builtins.set[str]:
        """Return the local task ids created by pull (imported remote items).

        These are tasks that *originate* from a user-created calendar event, so
        the push pass must not re-create them as doto-owned events (that would
        duplicate the item on the calendar). See
        :func:`doxtr_doto.calsync.engine.build_plan`.

        The ``builtins.set`` annotation is deliberate: this class defines a
        ``set`` *method*, which shadows the ``set`` builtin in the class-body
        annotation scope, so the fully-qualified name is required.
        """
        out: builtins.set[str] = set()
        for uid in self.imported_uids(provider, calendar):
            ref = self.get_imported(provider, calendar, uid)
            if ref is not None and ref.task_id:
                out.add(ref.task_id)
        return out

    def save(self) -> None:
        """Atomically persist state to disk."""
        if self._data is None:
            return
        self._data["updated"] = datetime.now().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            tmp.replace(self.path)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
