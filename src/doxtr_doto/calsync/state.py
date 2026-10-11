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
        updated: ISO timestamp of the last successful push.
    """

    uid: str
    etag: str = ""
    href: str = ""
    content_hash: str = ""
    remote_id: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "uid": self.uid,
            "etag": self.etag,
            "href": self.href,
            "content_hash": self.content_hash,
            "remote_id": self.remote_id,
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
                    "<task_id>": {"uid": ..., "etag": ..., "content_hash": ...},
                    ...
                },
                ...
            }
        }
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

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": CALSYNC_STATE_VERSION,
            "updated": datetime.now().isoformat(),
            "namespaces": {},
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
