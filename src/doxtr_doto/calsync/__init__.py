"""Calendar sync for doto tasks.

This package provides a provider-agnostic engine that projects doto tasks onto
remote calendar items (events or to-dos) and pushes them to a calendar server.

Layering (mirrors the RST ``sync`` package design):

* :mod:`doxtr_doto.calsync.model` - the provider-neutral ``CalendarEvent`` and
  the task -> event projection (workday/break-aware).
* :mod:`doxtr_doto.calsync.ical` - RFC 5545 (de)serialization via ``icalendar``.
* :mod:`doxtr_doto.calsync.state` - persisted per-task sync state
  (remote uid / etag / content hash) under ``.doto/calsync.json``.
* :mod:`doxtr_doto.calsync.engine` - the push-first sync engine + planning.
* :mod:`doxtr_doto.calsync.providers` - transport/auth per provider.
* :mod:`doxtr_doto.calsync.auth` - OAuth2 token cache helpers.

Heavy third-party dependencies (``caldav``, ``icalendar``, Google/MS SDKs) are
imported lazily inside the provider modules so core doto keeps working without
the optional ``[calendar]`` extra installed.
"""

from __future__ import annotations

from doxtr_doto.calsync.model import (
    CalendarEvent,
    EventKind,
    project,
    project_task_to_event,
    register_projector,
)

__all__ = [
    "CalendarEvent",
    "EventKind",
    "project",
    "project_task_to_event",
    "register_projector",
]
