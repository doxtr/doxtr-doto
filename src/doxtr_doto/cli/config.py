"""CLI configuration loading and mode detection."""

from __future__ import annotations

import os
import re as _re
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    VALID_PRIORITIES,
    VALID_STATUSES,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # Python <3.11 (pinned in pyproject)
    except ModuleNotFoundError:
        tomllib = None


class OperationMode(Enum):
    """CLI operation mode."""

    SPHINX = "sphinx"
    STANDALONE = "standalone"


#: Matches ``$VAR`` and ``${VAR}`` environment-variable references.
_ENV_VAR_RE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def resolve_env_vars(value: str) -> str:
    """Resolve ``$VAR`` and ``${VAR}`` references against the environment.

    Each reference is replaced with the corresponding environment variable's
    value, or the empty string when the variable is unset. Literal text is
    passed through unchanged. A value containing no reference is returned
    unchanged.

    Args:
        value: The raw string, possibly containing env-var references.

    Returns:
        The string with every reference resolved.

    Examples:
        >>> import os
        >>> os.environ["EXAMPLE_USER"] = "alice"
        >>> resolve_env_vars("$EXAMPLE_USER")
        'alice'
        >>> resolve_env_vars("${EXAMPLE_USER}")
        'alice'
        >>> resolve_env_vars("literal")
        'literal'
    """

    def _sub(match: _re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return os.environ.get(name, "")

    return _ENV_VAR_RE.sub(_sub, value)


def resolve_user(value: str) -> str:
    """Resolve the configured user value, falling back to ``$USER``.

    If ``value`` contains env-var references they are resolved via
    :func:`resolve_env_vars`. When the result is empty (no user configured),
    the OS ``$USER`` environment variable is used as a fallback.

    Args:
        value: The raw configured user (may be empty or contain ``$VAR``).

    Returns:
        The resolved user name, or the empty string when none can be found.
    """
    resolved = resolve_env_vars(value).strip() if value else ""
    if not resolved:
        resolved = os.environ.get("USER", "").strip()
    return resolved


#: Default working day boundaries and break window used when projecting a
#: date-only (all-day) due onto a concrete calendar time slot. These keep the
#: ``all-day`` -> timed-event projection sensible (a task "due today" lands in
#: the work day rather than at midnight). All naive/local, matching DotoDate.
DEFAULT_WORKDAY_START = "08:00"
DEFAULT_WORKDAY_END = "17:00"
DEFAULT_BREAK_START = "12:00"
DEFAULT_BREAK_END = "13:00"
DEFAULT_EVENT_DURATION_MINUTES = 30


@dataclass
class CalendarConfig:
    """Calendar-sync configuration (the ``[calendar]`` TOML table).

    Loaded independently of the flat :class:`DotoConfig` because calendar sync
    has a self-contained set of knobs (provider, auth, event projection) that
    only the ``doto calsync`` command group consumes. Keeping it separate
    avoids bloating the core config surface for users who never sync.

    All times are naive, local ``HH:MM`` strings, matching how doto models
    due dates/times (see :mod:`doxtr_doto.date_utils`). A timezone is attached
    only at the provider boundary.
    """

    #: Whether calendar sync is enabled at all.
    enabled: bool = False

    #: Provider id: ``"google"``, ``"microsoft"``, ``"apple"``, or ``"caldav"``.
    provider: str = ""

    #: Target calendar. For CalDAV/Apple this is the calendar collection URL or
    #: display name; for Google/Microsoft it is the calendar id (``"primary"``
    #: by default when empty).
    calendar: str = ""

    #: How a task is represented remotely:
    #:   * ``"event"`` - a VEVENT on the due date (visible in the calendar grid).
    #:   * ``"todo"``  - a VTODO item (a to-do, not a visible timed event).
    event_mode: str = "event"

    #: Sync direction. Only ``"push"`` (doto -> calendar) is implemented today;
    #: the engine is direction-aware so ``"two-way"`` can be enabled later.
    direction: str = "push"

    # --- Event-projection (event_mode == "event") --------------------------
    #: Duration (minutes) of the event created for a time-bearing due.
    event_duration_minutes: int = DEFAULT_EVENT_DURATION_MINUTES

    #: Working-day window. A date-only (all-day) due is projected to start at
    #: ``workday_start``; a timed due that would fall outside the window is left
    #: at its own time. These also bound the all-day "spread" behaviour.
    workday_start: str = DEFAULT_WORKDAY_START
    workday_end: str = DEFAULT_WORKDAY_END

    #: Daily break window carved out of the working day. An event whose time
    #: slot would overlap this window is pushed to ``break_end``.
    break_start: str = DEFAULT_BREAK_START
    break_end: str = DEFAULT_BREAK_END

    #: When True, a date-only due becomes a true all-day event instead of being
    #: projected onto ``workday_start``.
    all_day_for_dateless: bool = True

    # --- Auth --------------------------------------------------------------
    #: Provider endpoint URL (CalDAV base URL, or override for Google/MS).
    url: str = ""

    #: Username / account identifier (CalDAV, Apple ID email).
    username: str = ""

    #: Password or app-specific password (CalDAV / Apple). May use ``$VAR``
    #: references resolved against the environment; never store secrets in a
    #: committed config -- prefer an env var reference here.
    password: str = ""

    #: Path to an OAuth2 client-secrets JSON (Google / Microsoft). When empty,
    #: a bundled application client id is used if one is configured.
    oauth_client_secrets: str = ""

    def resolved_password(self) -> str:
        """Return the password with any ``$VAR`` references resolved."""
        return resolve_env_vars(self.password) if self.password else ""

    #: Accepted provider names/aliases (lowercased).
    _VALID_PROVIDERS = frozenset(
        {"google", "microsoft", "outlook", "ms", "graph", "apple", "icloud", "caldav"}
    )
    #: Accepted event-mode values.
    _VALID_EVENT_MODES = frozenset({"event", "todo"})
    #: Accepted sync directions (only "push" is implemented today).
    _VALID_DIRECTIONS = frozenset({"push"})

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems (empty if OK).

        Validation is intentionally performed on demand (by the ``calsync``
        commands) rather than at load time, matching the rest of the config
        loader which does not reject unknown values. This surfaces typos early
        with a clear message instead of a late failure deep in a provider.

        Returns:
            A list of error strings; empty when the config is usable.
        """
        errors: list[str] = []
        if self.provider and self.provider.lower() not in self._VALID_PROVIDERS:
            errors.append(
                f"Unknown calendar provider {self.provider!r}; expected one of: "
                "google, microsoft, apple, caldav."
            )
        if self.event_mode and self.event_mode.lower() not in self._VALID_EVENT_MODES:
            errors.append(f"Unknown event_mode {self.event_mode!r}; expected 'event' or 'todo'.")
        if self.direction and self.direction.lower() not in self._VALID_DIRECTIONS:
            errors.append(
                f"Unsupported direction {self.direction!r}; only 'push' is implemented "
                "(doto -> calendar). Two-way sync is planned."
            )
        return errors


@dataclass
class DotoConfig:
    """CLI configuration."""

    # Mode
    mode: OperationMode = OperationMode.SPHINX

    # Paths
    source_dir: Path = field(default_factory=lambda: Path.cwd())
    json_file: Path = field(default_factory=lambda: Path(".doto/tasks.json"))
    inbox_file: Path = field(default_factory=lambda: Path("tasks/inbox.rst"))
    conf_py: Path | None = None

    # Defaults
    default_priority: str = DEFAULT_PRIORITY
    default_status: str = DEFAULT_STATUS
    default_assignee: str = ""
    id_prefix: str = "DOTO"
    id_sequential: bool = True

    # Safety limits
    max_occurrences: int = 500  # Max recurring task occurrences per series

    # Display
    date_format: str = "%Y-%m-%d"
    editor: str = ""
    color: str = "auto"
    pager: str = "auto"
    list_columns: list[str] = field(
        default_factory=lambda: ["id", "priority", "status", "assignee", "due", "title"]
    )

    # Current user (for RACI auto-defaults)
    user: str = ""

    # Validation
    statuses: list[str] = field(default_factory=lambda: list(VALID_STATUSES))
    priorities: list[str] = field(default_factory=lambda: list(VALID_PRIORITIES))

    # Calendar sync (the ``[calendar]`` TOML table). Self-contained; only the
    # ``doto calsync`` command group reads it.
    calendar: CalendarConfig = field(default_factory=CalendarConfig)

    def get_json_path(self) -> Path:
        """Get the absolute path to the JSON store."""
        if self.json_file.is_absolute():
            return self.json_file
        return self.source_dir / self.json_file

    def get_inbox_path(self) -> Path:
        """Get the absolute path to the inbox file."""
        if self.inbox_file.is_absolute():
            return self.inbox_file
        return self.source_dir / self.inbox_file


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the project root by looking for .doto.toml or conf.py.

    Args:
        start: Starting directory (defaults to cwd).

    Returns:
        Project root path or None if not found.
    """
    current = start or Path.cwd()
    current = current.resolve()

    # Walk up the directory tree
    while current != current.parent:
        # Check for .doto.toml
        if (current / ".doto.toml").exists():
            return current
        # Check for conf.py (Sphinx project)
        if (current / "conf.py").exists():
            return current
        # Check for source/conf.py (common Sphinx layout)
        if (current / "source" / "conf.py").exists():
            return current
        # Check for docs/conf.py (another common layout)
        if (current / "docs" / "conf.py").exists():
            return current
        current = current.parent

    return None


def find_conf_py(project_root: Path) -> Path | None:
    """Find conf.py in a Sphinx project.

    Args:
        project_root: Project root directory.

    Returns:
        Path to conf.py or None if not found.
    """
    candidates = [
        project_root / "conf.py",
        project_root / "source" / "conf.py",
        project_root / "docs" / "conf.py",
        project_root / "docs" / "source" / "conf.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def detect_mode(
    config_path: Path | None = None, json_path: Path | None = None
) -> tuple[OperationMode, Path | None]:
    """Determine CLI operation mode.

    Priority:
    1. --json flag → Standalone mode with specified JSON
    2. --config flag → Sphinx mode with specified project
    3. .doto.toml in cwd or parents → Sphinx mode
    4. conf.py in cwd or parents → Sphinx mode
    5. ~/.doto/config.toml exists → Standalone mode
    6. Default → Sphinx mode, create .doto/ in cwd

    Args:
        config_path: Explicit config path from --config flag.
        json_path: Explicit JSON path from --json flag.

    Returns:
        Tuple of (mode, project_root).
    """
    # 1. --json flag → Standalone mode
    if json_path is not None:
        return OperationMode.STANDALONE, None

    # 2. --config flag → Sphinx mode with specified project
    if config_path is not None:
        config_path = Path(config_path).resolve()
        if config_path.is_file():
            return OperationMode.SPHINX, config_path.parent
        return OperationMode.SPHINX, config_path

    # 3. .doto.toml in cwd or parents → Sphinx mode
    project_root = find_project_root()
    if project_root is not None:
        return OperationMode.SPHINX, project_root

    # 4. ~/.doto/config.toml exists → Standalone mode
    user_config = Path.home() / ".doto" / "config.toml"
    if user_config.exists():
        return OperationMode.STANDALONE, None

    # 5. Default → Sphinx mode, create .doto/ in cwd
    return OperationMode.SPHINX, Path.cwd()


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file.

    Args:
        path: Path to TOML file.

    Returns:
        Parsed TOML content.
    """
    if tomllib is None:
        raise ImportError(
            "A TOML parser is required for TOML parsing. On Python 3.11+ this is the "
            "stdlib 'tomllib'; on older Pythons install 'tomli' (pip install tomli)."
        )
    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)
        return data


def _warn_config_error(path: Path, exc: Exception) -> None:
    """Emit a warning for a config loading failure.

    Args:
        path: Path to the config file that failed to load.
        exc: The exception that was raised.
    """
    warnings.warn(
        f"doto: Failed to load config from {path}: {exc}. Using defaults for this file.",
        stacklevel=3,
    )


def load_sphinx_config(conf_py: Path) -> dict[str, Any]:
    """Load doto configuration from Sphinx conf.py.

    This function executes the conf.py file to extract configuration values,
    matching Sphinx's own behavior. This is safe because:

    1. conf.py is a user-controlled file in their own project
    2. Users already trust this file (Sphinx executes it during builds)
    3. The CLI operates with the user's own permissions

    Security Note:
        Do not use this function on untrusted conf.py files.
        This is designed for local development use only.

    Args:
        conf_py: Path to conf.py file.

    Returns:
        Dictionary of doto_* config values.
    """
    config: dict[str, Any] = {}

    # Create namespace with __file__ and __name__ for better error messages
    # This matches Sphinx's own approach when loading conf.py
    namespace: dict[str, Any] = {
        "__builtins__": __builtins__,
        "__file__": str(conf_py),
        "__name__": "__conf__",
    }

    try:
        # Read and compile for better error messages with line numbers
        code = conf_py.read_text(encoding="utf-8")
        compiled = compile(code, str(conf_py), "exec")
        exec(compiled, namespace)  # noqa: S102 - Standard Sphinx pattern for conf.py
    except SyntaxError as exc:
        warnings.warn(
            f"doto: Syntax error in {conf_py}: {exc}. "
            "Sphinx config values will not be applied to CLI.",
            stacklevel=2,
        )
        return config
    except Exception as exc:
        warnings.warn(
            f"doto: Failed to exec {conf_py}: {exc}. "
            "Sphinx config values will not be applied to CLI.",
            stacklevel=2,
        )
        return config

    # Extract only doto_* values (don't expose other config)
    for key, value in namespace.items():
        if key.startswith("doto_"):
            # Remove doto_ prefix
            config_key = key[5:]
            config[config_key] = value

    return config


def load_config(
    config_path: Path | None = None,
    json_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> DotoConfig:
    """Load configuration from all sources.

    Configuration hierarchy (highest to lowest):
    1. Command-line arguments
    2. Environment variables (DOTO_*)
    3. Project config (.doto.toml in cwd or parents)
    4. User config (~/.doto/config.toml)
    5. Sphinx conf.py values
    6. Built-in defaults

    Args:
        config_path: Explicit config path from --config flag.
        json_path: Explicit JSON path from --json flag.
        cli_overrides: CLI argument overrides.

    Returns:
        Merged configuration.
    """
    mode, project_root = detect_mode(config_path, json_path)
    config = DotoConfig(mode=mode)

    # Start with defaults (already set)

    # Load user config (~/.doto/config.toml)
    user_config_path = Path.home() / ".doto" / "config.toml"

    # Check for project .doto.toml path early for TOML-parser check
    project_toml = (project_root / ".doto.toml") if project_root else None

    # Pre-check for a missing TOML parser when TOML files exist
    toml_files_exist = user_config_path.exists() or (
        project_toml is not None and project_toml.exists()
    )
    if toml_files_exist and tomllib is None:
        warnings.warn(
            "doto: no TOML parser available; .toml config files cannot be loaded. "
            "On Python 3.11+ 'tomllib' is in the stdlib; on older Pythons install "
            "'tomli' (pip install tomli).",
            stacklevel=2,
        )

    if user_config_path.exists():
        try:
            user_config = load_toml(user_config_path)
            _apply_toml_config(config, user_config.get("doto", {}))
            _apply_calendar_config(config, user_config.get("calendar", {}))
        except Exception as exc:
            _warn_config_error(user_config_path, exc)

    # In Sphinx mode, load from project sources
    if mode == OperationMode.SPHINX and project_root:
        config.source_dir = project_root

        # Load Sphinx conf.py if available
        conf_py = find_conf_py(project_root)
        if conf_py:
            config.conf_py = conf_py
            sphinx_config = load_sphinx_config(conf_py)
            _apply_sphinx_config(config, sphinx_config)
            # Update source_dir to be the directory containing conf.py
            config.source_dir = conf_py.parent

        # Load project .doto.toml (overrides conf.py)
        if project_toml is not None and project_toml.exists():
            try:
                project_config = load_toml(project_toml)
                _apply_toml_config(config, project_config.get("doto", {}))
                _apply_calendar_config(config, project_config.get("calendar", {}))
            except Exception as exc:
                _warn_config_error(project_toml, exc)

    # Apply environment variables (DOTO_*)
    _apply_env_config(config)

    # Apply CLI overrides
    if cli_overrides:
        _apply_cli_overrides(config, cli_overrides)

    # Handle explicit --json flag for standalone mode
    if json_path:
        config.json_file = Path(json_path)
        if not config.json_file.is_absolute():
            config.json_file = Path.cwd() / config.json_file

    return config


def _apply_toml_config(config: DotoConfig, toml_config: dict[str, Any]) -> None:
    """Apply TOML configuration to config object."""
    if "source_dir" in toml_config:
        config.source_dir = Path(toml_config["source_dir"])
    if "json_file" in toml_config:
        config.json_file = Path(toml_config["json_file"])
    if "inbox_file" in toml_config:
        config.inbox_file = Path(toml_config["inbox_file"])
    if "default_priority" in toml_config:
        config.default_priority = toml_config["default_priority"]
    if "default_status" in toml_config:
        config.default_status = toml_config["default_status"]
    if "default_assignee" in toml_config:
        config.default_assignee = toml_config["default_assignee"]
    if "id_prefix" in toml_config:
        config.id_prefix = toml_config["id_prefix"]
    if "id_sequential" in toml_config:
        config.id_sequential = toml_config["id_sequential"]
    if "max_occurrences" in toml_config:
        config.max_occurrences = int(toml_config["max_occurrences"])
    if "date_format" in toml_config:
        config.date_format = toml_config["date_format"]
    if "editor" in toml_config:
        config.editor = toml_config["editor"]
    if "color" in toml_config:
        config.color = toml_config["color"]
    if "pager" in toml_config:
        config.pager = toml_config["pager"]
    if "list_columns" in toml_config:
        config.list_columns = list(toml_config["list_columns"])
    if "statuses" in toml_config:
        config.statuses = list(toml_config["statuses"])
    if "priorities" in toml_config:
        config.priorities = list(toml_config["priorities"])
    if "user" in toml_config:
        config.user = toml_config["user"]


def _apply_calendar_config(config: DotoConfig, cal: dict[str, Any]) -> None:
    """Apply the ``[calendar]`` TOML table to ``config.calendar``.

    Only known keys are copied; unknown keys are ignored so forward-compatible
    configs don't error on an older doto. String/int/bool values are coerced
    to the dataclass field types.
    """
    if not cal:
        return
    cc = config.calendar
    str_keys = (
        "provider",
        "calendar",
        "event_mode",
        "direction",
        "workday_start",
        "workday_end",
        "break_start",
        "break_end",
        "url",
        "username",
        "password",
        "oauth_client_secrets",
    )
    for key in str_keys:
        if key in cal:
            setattr(cc, key, str(cal[key]))
    if "enabled" in cal:
        cc.enabled = bool(cal["enabled"])
    if "all_day_for_dateless" in cal:
        cc.all_day_for_dateless = bool(cal["all_day_for_dateless"])
    if "event_duration_minutes" in cal:
        cc.event_duration_minutes = int(cal["event_duration_minutes"])


def _apply_sphinx_config(config: DotoConfig, sphinx_config: dict[str, Any]) -> None:
    """Apply Sphinx configuration to config object."""
    if "json_file" in sphinx_config:
        config.json_file = Path(sphinx_config["json_file"])
    if "inbox_file" in sphinx_config:
        config.inbox_file = Path(sphinx_config["inbox_file"])
    if "default_priority" in sphinx_config:
        config.default_priority = sphinx_config["default_priority"]
    if "default_status" in sphinx_config:
        config.default_status = sphinx_config["default_status"]
    if "statuses" in sphinx_config:
        config.statuses = list(sphinx_config["statuses"])
    if "priorities" in sphinx_config:
        config.priorities = list(sphinx_config["priorities"])
    if "date_format" in sphinx_config:
        config.date_format = sphinx_config["date_format"]
    if "id_prefix" in sphinx_config:
        config.id_prefix = sphinx_config["id_prefix"]
    if "list_columns" in sphinx_config:
        config.list_columns = list(sphinx_config["list_columns"])
    if "default_user" in sphinx_config:
        config.user = sphinx_config["default_user"]


def _apply_env_config(config: DotoConfig) -> None:
    """Apply environment variable configuration."""
    env_mappings: dict[str, tuple[str, Callable[[str], Any]]] = {
        "DOTO_JSON_FILE": ("json_file", Path),
        "DOTO_INBOX_FILE": ("inbox_file", Path),
        "DOTO_DEFAULT_PRIORITY": ("default_priority", str),
        "DOTO_DEFAULT_STATUS": ("default_status", str),
        "DOTO_DEFAULT_ASSIGNEE": ("default_assignee", str),
        "DOTO_ID_PREFIX": ("id_prefix", str),
        "DOTO_DATE_FORMAT": ("date_format", str),
        "DOTO_EDITOR": ("editor", str),
        "DOTO_COLOR": ("color", str),
        "DOTO_LIST_COLUMNS": ("list_columns", lambda x: x.split(",")),
        "DOTO_MAX_OCCURRENCES": ("max_occurrences", int),
        "DOTO_USER": ("user", str),
    }

    for env_var, (attr, converter) in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            setattr(config, attr, converter(value))


def _apply_cli_overrides(config: DotoConfig, overrides: dict[str, Any]) -> None:
    """Apply CLI argument overrides."""
    for key, value in overrides.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
