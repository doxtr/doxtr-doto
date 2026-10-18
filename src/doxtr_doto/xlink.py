"""Render-time resolution of ``:xlink:`key``` tokens via doxtr-xlink.

The doto ``:assignee:`` field can carry :mod:`doxtr_xlink` references,
e.g.::

    .. doto:: Document the decision
       :assignee: :xlink:`yourdirectory-person-alice-bobbington`

Which fields resolve is data-driven via :data:`doxtr_doto.fields.XLINK_FIELDS`
(derived from ``FieldDefinition.resolves_xlinks``); today that is the
``:assignee:`` field only. ``:body:`` is intentionally excluded because it is
parsed as reST, and ``:title:`` is excluded because it also serves as cross-
reference link text — enabling another plain-text field is a one-line flag
change in ``fields.py`` with no edits to this module or the render seams.

By default doto stores and renders those field values as the raw literal string
(``":xlink:`yourdirectory-person-alice-bobbington`"``). When the optional
``doxtr-xlink`` package is installed *and* enabled, this module resolves
such tokens to the human-readable display name (and link URL where meaningful)
using doxtr-xlink's own resolver API, exactly like the plotly path in
:mod:`doxtr_doto.charts` degrades gracefully when its optional dependency is
absent.

Resolution happens at RENDER time only. The stored JSON / RST keep the raw
``:xlink:`` token so sync round-trips stay byte-stable; nothing here mutates the
task store.

Overridable seams (modularity)
------------------------------
All xlink knowledge lives in this one module. Render code (``nodes.py``, the CLI
and the TUI) must call :func:`resolve_xlink_tokens` / :func:`resolve_xlink_text`
and never parse ``:xlink:`` tokens inline. Two documented seams let a child
theme or downstream project swap behavior without touching render code:

* :data:`XLINK_TOKEN_RE` + :func:`iter_xlink_tokens` — the single place token
  syntax is parsed. Reuse these if you need to find tokens yourself.
* :func:`_get_resolver_fn` — the single indirection point for the resolver.
  It returns a ``(key) -> (title, url)`` callable (or ``None`` when xlink is
  unavailable/disabled). Monkeypatch or reassign this to plug in a custom
  resolver (e.g. a project-specific directory, or a stubbed resolver in tests)
  without editing any render seam. The Sphinx build path uses
  ``doxtr_xlink._get_xlink_data``; the app-less CLI/TUI path uses
  :func:`_appless_resolver` which scans the ``.xlink`` directory directly.

Keeping these the lone seams means a swap is a one-function change and callers
have exactly one hook each.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, NamedTuple, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sphinx.application import Sphinx

#: Regex matching a single ``:xlink:`key``` role token.
#:
#: The captured group ``key`` is the raw xlink expression between the backticks,
#: which may be a bare key (``yourdirectory-person-alice-bobbington``) or xlink's
#: ``Label <key>`` form. This is the ONE place token syntax is defined; reuse it
#: (via :func:`iter_xlink_tokens`) instead of re-deriving the pattern.
XLINK_TOKEN_RE = re.compile(r":xlink:`(?P<key>[^`]+)`")


class ResolvedField(NamedTuple):
    """Result of resolving every ``:xlink:`` token in a field value.

    Attributes:
        display: The field text with every ``:xlink:`key``` token replaced by
            its resolved title (or the raw key when unresolved / xlink absent).
            Non-token text is preserved verbatim.
        links: Ordered ``(title, url)`` pairs for tokens that resolved to a URL,
            for renderers that can emit hyperlinks (HTML/LaTeX). Empty when no
            token resolved to a URL (or xlink is absent). Entries are in token
            order and are not deduplicated; the bundled renderers use the first
            link as the field's single href (see :func:`resolve_field_value`).
    """

    display: str
    links: list[tuple[str, str]]


def iter_xlink_tokens(text: str) -> Iterator[re.Match[str]]:
    """Yield each ``:xlink:`key``` match in ``text``.

    The single public entry point for finding xlink tokens, built on
    :data:`XLINK_TOKEN_RE`. A child theme that needs its own token handling can
    reuse this rather than re-deriving the pattern.
    """
    return XLINK_TOKEN_RE.finditer(text)


def contains_xlink_token(text: str) -> bool:
    """Return True when ``text`` contains at least one ``:xlink:`` token."""
    return bool(text) and XLINK_TOKEN_RE.search(text) is not None


def _normalize_key(raw_key: str) -> str:
    """Reduce an xlink expression to its lookup key.

    Accepts xlink's ``Label <key>`` form (returning ``key``) or a bare key
    (returned as-is). Mirrors the key extraction in
    :func:`doxtr_xlink.roles.xlink_role` so doto resolves the same key
    xlink would.
    """
    match = re.search(r"^(?P<label>.*?)\s*<(?P<key>[^<>]+)>$", raw_key)
    if match:
        return match.group("key").strip()
    return raw_key.strip().strip("` ")


def _xlink_enabled(app: Sphinx | None) -> bool:
    """Return True when xlink resolution should run for this Sphinx app.

    All three conditions must hold (graceful degradation otherwise):

    1. ``doto_resolve_xlinks`` config is truthy.
    2. ``doxtr_xlink`` is listed in ``app.config.extensions``.
    3. ``doxtr_xlink`` is importable with a usable resolver symbol.
    """
    if app is None:
        return False
    from doxtr_doto.config import get_config

    if not get_config(app, "resolve_xlinks"):
        return False
    extensions = getattr(app.config, "extensions", []) or []
    if "doxtr_xlink" not in extensions:
        return False
    return _import_xlink_resolver() is not None


def _import_xlink_resolver() -> Callable[..., tuple[Any, Any]] | None:
    """Import xlink's ``_get_xlink_data`` resolver, or ``None`` if unavailable.

    Isolated so a missing package or a future-renamed symbol never breaks a
    build and so tests can monkeypatch it. Mirrors the import guard in
    :func:`doxtr_doto.charts.plotly_available`.
    """
    try:
        from doxtr_xlink import _get_xlink_data
    except Exception:
        return None
    if not callable(_get_xlink_data):
        return None
    return cast("Callable[..., tuple[Any, Any]]", _get_xlink_data)


def _appless_resolver(xlink_dir: str) -> Callable[[str], tuple[str | None, str | None]]:
    """Build a resolver that scans ``.xlink`` files without a Sphinx app.

    The CLI/TUI operate on ``tasks.json`` with no running Sphinx build, so
    xlink's ``_get_xlink_data(app, ...)`` is not usable there. This replicates
    the minimal ``.xlink`` file scan (``key :: title :: url`` lines) so CLI/TUI
    output can still show resolved names. Returns ``(None, None)`` for any key
    that is not found.

    Args:
        xlink_dir: Directory to scan recursively for ``*.xlink`` files.

    Returns:
        A ``(key) -> (title, url)`` callable.
    """
    # ``.xlink`` grammar: ``key :: title :: url`` lines (``#`` comments / blanks
    # skipped). This intentionally mirrors doxtr-xlink's own ``.xlink``
    # file grammar and must track upstream if that grammar changes.
    table: dict[str, tuple[str, str]] = {}
    if os.path.isdir(xlink_dir):
        for root, dirs, files in os.walk(xlink_dir):
            if ".xlink" in dirs:
                dirs.remove(".xlink")
            for filename in files:
                if not filename.endswith(".xlink"):
                    continue
                path = os.path.join(root, filename)
                try:
                    with open(path, encoding="utf-8-sig") as fh:
                        for line in fh:
                            clean = line.strip()
                            if not clean or clean.startswith("#"):
                                continue
                            if " :: " in clean:
                                parts = [p.strip() for p in clean.split(" :: ", 3)]
                                if len(parts) >= 3:
                                    table[parts[0]] = (parts[1], parts[2])
                except OSError:
                    continue

    def _resolve(key: str) -> tuple[str | None, str | None]:
        entry = table.get(key)
        if entry is None:
            return None, None
        return entry

    return _resolve


def _get_resolver_fn(
    app: Sphinx | None = None,
    xlink_dir: str | None = None,
) -> Callable[[str], tuple[str | None, str | None]] | None:
    """Return the ``(key) -> (title, url)`` resolver callable, or ``None``.

    THE single indirection point for the resolver (modularity seam). Render code
    always obtains its resolver here, so a downstream project can monkeypatch
    this function to swap in a custom resolver without touching any render seam.

    Two modes:

    * Sphinx build (``app`` given, xlink enabled): wraps
      ``doxtr_xlink._get_xlink_data(app, key)``.
    * App-less (``xlink_dir`` given, no app): uses :func:`_appless_resolver` to
      scan the ``.xlink`` directory directly (CLI/TUI).

    Returns ``None`` when resolution is unavailable/disabled so callers degrade
    to rendering the raw token.
    """
    if app is not None:
        if not _xlink_enabled(app):
            return None
        resolver = _import_xlink_resolver()
        if resolver is None:
            return None

        def _resolve_with_app(key: str) -> tuple[str | None, str | None]:
            try:
                title, url = resolver(app, key)
            except Exception:
                return None, None
            return title, url

        return _resolve_with_app

    if xlink_dir is not None:
        return _appless_resolver(xlink_dir)

    return None


def _resolve_with(
    text: str,
    resolver: Callable[[str], tuple[str | None, str | None]] | None,
) -> ResolvedField:
    """Replace every ``:xlink:`` token in ``text`` using ``resolver``.

    Shared core for :func:`resolve_xlink_tokens` (Sphinx) and
    :func:`resolve_xlink_text` (app-less). When ``resolver`` is ``None`` or a
    token does not resolve, the token is replaced by its bare key (readable
    fallback) and contributes no link.
    """
    if not text or not contains_xlink_token(text):
        return ResolvedField(display=text, links=[])

    links: list[tuple[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        key = _normalize_key(match.group("key"))
        title: str | None = None
        url: str | None = None
        if resolver is not None:
            title, url = resolver(key)
        display = title if title else key
        if title and url:
            links.append((title, url))
        return display

    display = XLINK_TOKEN_RE.sub(_replace, text)
    return ResolvedField(display=display, links=links)


def resolve_xlink_tokens(app: Sphinx | None, text: str) -> ResolvedField:
    """Resolve ``:xlink:`key``` tokens in ``text`` for a Sphinx build.

    Args:
        app: The Sphinx application (its config/extensions decide whether
            resolution runs). ``None`` disables resolution.
        text: The raw field value, possibly containing ``:xlink:`` tokens.

    Returns:
        A :class:`ResolvedField`. When xlink is absent/disabled (no resolver),
        ``display`` equals ``text`` unchanged and ``links`` is empty — the raw
        ``:xlink:`` token is rendered exactly as today. When resolution is
        active but a key is unresolved, that token reduces to its bare key. The
        input ``text`` is never mutated in the store — resolution is
        render-time only.
    """
    resolver = _get_resolver_fn(app=app)
    if resolver is None:
        # Resolution disabled/unavailable: render the raw token unchanged.
        return ResolvedField(display=text, links=[])
    return _resolve_with(text, resolver)


def resolve_field_value(app: Sphinx | None, value: str) -> tuple[str, str | None]:
    """Return ``(display_text, first_url_or_None)`` for a field value.

    Encapsulates the bundled-renderer convention that a resolved field links to
    the FIRST resolved token's URL (if any). The single place render seams
    (HTML/LaTeX, single-task and list cells) collapse a :class:`ResolvedField`
    into the ``(display, href)`` pair they emit, so that convention lives in one
    spot. Child themes needing per-token links should call
    :func:`resolve_xlink_tokens` and read :attr:`ResolvedField.links` directly.
    """
    resolved = resolve_xlink_tokens(app, value)
    url = resolved.links[0][1] if resolved.links else None
    return resolved.display, url


def resolve_xlink_text(text: str, xlink_dir: str | None) -> str:
    """Resolve ``:xlink:`` tokens to plain display text without a Sphinx app.

    For CLI/TUI output, which has no running Sphinx build. Scans ``xlink_dir``
    for ``.xlink`` definitions; when the directory is unknown/missing the raw
    token is returned unchanged, and when a key is not found that token degrades
    to its bare key.

    Args:
        text: The raw field value.
        xlink_dir: Directory containing ``.xlink`` files, or ``None`` to skip
            lookup entirely (the raw token is returned unchanged).

    Returns:
        The display text with tokens replaced.
    """
    if not xlink_dir:
        return text
    resolver = _get_resolver_fn(xlink_dir=xlink_dir)
    return _resolve_with(text, resolver).display
