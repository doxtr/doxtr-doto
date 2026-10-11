"""Abstract base class and shared types for calendar providers."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxtr_doto.calsync.model import CalendarEvent
    from doxtr_doto.cli.config import CalendarConfig


class ProviderError(RuntimeError):
    """A provider-level failure (network, protocol, server error)."""


class ProviderAuthError(ProviderError):
    """Authentication/authorization failed or credentials are missing."""


@dataclass
class PushResult:
    """Outcome of creating or updating a single remote item.

    Attributes:
        uid: iCalendar UID of the item.
        etag: Server ETag after the write (empty if the server didn't return one).
        href: CalDAV resource URL (empty for API providers).
        remote_id: Provider-native id (empty for CalDAV).
    """

    uid: str
    etag: str = ""
    href: str = ""
    remote_id: str = ""


class CalendarProvider(abc.ABC):
    """Transport/auth interface the sync engine drives.

    Lifecycle: construct with a :class:`~doxtr_doto.cli.config.CalendarConfig`,
    call :meth:`connect` once (authenticates and resolves the target calendar),
    then issue :meth:`create_event` / :meth:`update_event` / :meth:`delete_event`.

    Implementations must be idempotent on ``uid``: creating an item whose UID
    already exists should behave like an update (or the engine's state tracking
    will prevent the situation in the common case).
    """

    #: Human-readable provider id, e.g. ``"google"``.
    name: str = "base"

    def __init__(self, config: CalendarConfig) -> None:
        """Store config; defer all network/auth work to :meth:`connect`."""
        self.config = config

    @abc.abstractmethod
    def connect(self) -> None:
        """Authenticate and resolve the target calendar.

        Raises:
            ProviderAuthError: If credentials are missing or rejected.
            ProviderError: On other connection failures.
        """

    @abc.abstractmethod
    def create_event(self, event: CalendarEvent) -> PushResult:
        """Create a new remote item from ``event`` and return its identifiers."""

    @abc.abstractmethod
    def update_event(self, event: CalendarEvent, *, etag: str = "", href: str = "") -> PushResult:
        """Update the existing remote item identified by ``event.uid``.

        Args:
            event: The new desired state.
            etag: Last-seen ETag for a conditional (If-Match) update when supported.
            href: Opaque remote locator for the item -- a CalDAV resource URL
                for CalDAV providers, or the provider-native id (Google/MS
                event id) for API providers. May be empty, in which case the
                provider resolves the item from ``event.uid``.
        """

    @abc.abstractmethod
    def delete_event(self, uid: str, *, etag: str = "", href: str = "") -> None:
        """Delete the remote item identified by ``uid`` (and/or ``href``).

        ``href`` is the same opaque remote locator described on
        :meth:`update_event` (CalDAV URL or provider-native id); when empty the
        provider resolves the item from ``uid``.
        """
