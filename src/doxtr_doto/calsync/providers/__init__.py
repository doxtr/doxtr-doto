"""Calendar provider transport layer.

Each provider implements a small, synchronous interface the engine drives:
authenticate, then create/update/delete calendar items. The engine is entirely
provider-agnostic; all protocol- and auth-specific logic lives here.

Provider modules import their heavy SDKs lazily so that importing this package
(and running the non-calendar parts of doto) never requires the optional
``[calendar]`` dependencies.

Extensibility
-------------
Providers are looked up through an open registry (:func:`register_provider` /
:func:`get_provider`) rather than a hard-coded switch, mirroring the project's
other downstream-extension points (``register_restore_strategy`` in
:mod:`doxtr_doto.sync.restore` and ``register_directive_renderer`` in
:mod:`doxtr_doto.sync.rst_writer`). A child project or third party can register
an additional or replacement calendar provider **without editing core**::

    from doxtr_doto.calsync.providers import register_provider

    def _load_my_provider():
        from my_pkg.calsync import MyProvider
        return MyProvider

    register_provider("myprovider", _load_my_provider)

The loader is a zero-argument callable returning a
:class:`~doxtr_doto.calsync.providers.base.CalendarProvider` subclass; wrapping
the import in a loader preserves the lazy-import contract (the provider's SDK is
only imported when that provider is actually selected).
"""

from __future__ import annotations

from collections.abc import Callable

from doxtr_doto.calsync.providers.base import (
    CalendarProvider,
    ProviderAuthError,
    ProviderError,
    PushResult,
)

__all__ = [
    "CalendarProvider",
    "ProviderError",
    "ProviderAuthError",
    "PushResult",
    "get_provider",
    "register_provider",
]

#: Registry mapping a lowercased provider name/alias to a zero-arg loader that
#: returns a :class:`CalendarProvider` subclass. Populated with the built-ins at
#: import time; extendable at runtime via :func:`register_provider`.
_PROVIDERS: dict[str, Callable[[], type[CalendarProvider]]] = {}


def register_provider(name: str, loader: Callable[[], type[CalendarProvider]]) -> None:
    """Register (or override) a calendar-provider loader under ``name``.

    Downstream extension point: a child project can add an alternative or
    additional calendar provider without editing core. The ``loader`` is a
    zero-argument callable returning a :class:`CalendarProvider` subclass;
    wrapping the import inside the loader keeps the provider's SDK lazily
    imported (only loaded when that provider is selected).

    Args:
        name: Provider name or alias (matched case-insensitively).
        loader: Zero-arg callable returning the provider class.
    """
    _PROVIDERS[name.strip().lower()] = loader


def get_provider(name: str) -> type[CalendarProvider]:
    """Return the provider class registered under ``name`` (lazy import).

    Args:
        name: One of the registered names/aliases (e.g. ``"google"``,
            ``"microsoft"``/``"outlook"``, ``"apple"``/``"icloud"``,
            ``"caldav"``), matched case-insensitively.

    Returns:
        A :class:`CalendarProvider` subclass (not an instance).

    Raises:
        ValueError: If ``name`` is not a registered provider.
    """
    key = (name or "").strip().lower()
    loader = _PROVIDERS.get(key)
    if loader is None:
        known = ", ".join(sorted(_PROVIDERS)) or "(none registered)"
        raise ValueError(f"Unknown calendar provider {name!r}. Known providers: {known}.")
    return loader()


# -- Built-in provider loaders (kept lazy via wrapping functions) ------------
def _load_caldav() -> type[CalendarProvider]:
    from doxtr_doto.calsync.providers.caldav import CalDAVProvider

    return CalDAVProvider


def _load_google() -> type[CalendarProvider]:
    from doxtr_doto.calsync.providers.google import GoogleCalendarProvider

    return GoogleCalendarProvider


def _load_microsoft() -> type[CalendarProvider]:
    from doxtr_doto.calsync.providers.microsoft import MicrosoftCalendarProvider

    return MicrosoftCalendarProvider


for _alias in ("caldav", "apple", "icloud"):
    register_provider(_alias, _load_caldav)
register_provider("google", _load_google)
for _alias in ("microsoft", "outlook", "ms", "graph"):
    register_provider(_alias, _load_microsoft)
