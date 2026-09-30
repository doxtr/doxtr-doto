"""CLI configuration loading and mode detection."""

from __future__ import annotations

import os
import warnings
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

try:
    import tomli
except ImportError:
    tomli = None  # type: ignore[assignment]


class OperationMode(Enum):
    """CLI operation mode."""

    SPHINX = "sphinx"
    STANDALONE = "standalone"


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

    # Validation
    statuses: list[str] = field(
        default_factory=lambda: list(VALID_STATUSES)
    )
    priorities: list[str] = field(
        default_factory=lambda: list(VALID_PRIORITIES)
    )

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
    if tomli is None:
        raise ImportError(
            "tomli is required for TOML parsing. Install with: pip install tomli"
        )
    with open(path, "rb") as f:
        return tomli.load(f)


def _warn_config_error(path: Path, exc: Exception) -> None:
    """Emit a warning for a config loading failure.

    Args:
        path: Path to the config file that failed to load.
        exc: The exception that was raised.
    """
    warnings.warn(
        f"doto: Failed to load config from {path}: {exc}. "
        "Using defaults for this file.",
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
    
    # Check for project .doto.toml path early for tomli check
    project_toml = (project_root / ".doto.toml") if project_root else None
    
    # Pre-check for missing tomli when TOML files exist
    toml_files_exist = (
        user_config_path.exists() or 
        (project_toml is not None and project_toml.exists())
    )
    if toml_files_exist and tomli is None:
        warnings.warn(
            "doto: tomli is not installed; .toml config files cannot be loaded. "
            "Install with: pip install tomli",
            stacklevel=2,
        )
    
    if user_config_path.exists():
        try:
            user_config = load_toml(user_config_path)
            _apply_toml_config(config, user_config.get("doto", {}))
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


def _apply_env_config(config: DotoConfig) -> None:
    """Apply environment variable configuration."""
    env_mappings = {
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
