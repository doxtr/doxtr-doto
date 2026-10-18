"""OAuth2 token cache helpers for API-based providers (Google, Microsoft).

Tokens are per-user and must survive across CLI invocations, so they are cached
on disk under the user's config dir. The cache is namespaced by provider so a
user can be logged into Google and Microsoft at once.

Location (first that applies):

1. ``$DOTO_CONFIG`` directory, if that env var points at a config file.
2. ``$XDG_CONFIG_HOME/doto`` (falling back to ``~/.config/doto``).

The directory is created ``0700`` and token files ``0600`` so cached refresh
tokens are not world-readable.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "DOTO_CONFIG"

#: Provider-name/alias -> cached-token name. Several user-facing provider names
#: are aliases of the same backend (Apple/iCloud both use the CalDAV token;
#: Outlook/MS/Graph all map to the Microsoft token), so logout must normalize
#: an alias to the name the token was saved under. Centralized here so the CLI
#: (``doto calsync logout``) and the TUI (``C o``) cannot drift.
_TOKEN_NAME_ALIASES: dict[str, str] = {
    "apple": "caldav",
    "icloud": "caldav",
    "outlook": "microsoft",
    "ms": "microsoft",
    "graph": "microsoft",
}


def canonical_token_name(provider: str) -> str:
    """Return the cached-token name for a provider name/alias.

    Folds user-facing aliases (``apple``/``icloud`` -> ``caldav``;
    ``outlook``/``ms``/``graph`` -> ``microsoft``) onto the name the token was
    actually saved under, so :func:`clear_token` targets the right file. A
    provider with no alias (e.g. ``google``, ``caldav``) is returned unchanged.

    Args:
        provider: The configured provider name or an alias.

    Returns:
        The canonical token name to pass to :func:`clear_token` / token I/O.
    """
    return _TOKEN_NAME_ALIASES.get(provider, provider)


def token_dir() -> Path:
    """Return (and create, 0700) the directory holding OAuth token caches."""
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        base = Path(env).expanduser().parent
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg).expanduser() / "doto" if xdg else Path.home() / ".config" / "doto"
    tokens = base / "calsync-tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    try:
        tokens.chmod(stat.S_IRWXU)  # 0700
    except OSError:  # pragma: no cover - platform dependent
        pass
    return tokens


def token_path(provider: str) -> Path:
    """Return the token-cache file path for ``provider``."""
    safe = "".join(c for c in provider if c.isalnum() or c in "-_") or "provider"
    return token_dir() / f"{safe}.json"


def load_token(provider: str) -> dict[str, Any] | None:
    """Load the cached token dict for ``provider``, or None if absent/invalid."""
    path = token_path(provider)
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_token(provider: str, token: dict[str, Any]) -> None:
    """Persist ``token`` for ``provider`` with 0600 permissions (atomic)."""
    path = token_path(provider)
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(token, f, indent=2)
            f.write("\n")
        try:
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:  # pragma: no cover
            pass
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def clear_token(provider: str) -> bool:
    """Delete the cached token for ``provider``. Returns True if one existed."""
    path = token_path(provider)
    if path.exists():
        path.unlink()
        return True
    return False
