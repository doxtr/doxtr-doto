"""Config-aware validators for CLI options.

These validators read allowed values from config at runtime,
allowing customization of valid statuses and priorities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from click import Context, Parameter


def _get_config_values(ctx: Context, config_attr: str, defaults: list[str]) -> list[str]:
    """Get allowed values from config or use defaults.

    Args:
        ctx: Click context.
        config_attr: Attribute name on config (e.g., 'statuses', 'priorities').
        defaults: Default values if config not available.

    Returns:
        List of allowed values.
    """
    # Try to get from context
    if ctx and ctx.obj:
        config = getattr(ctx.obj, "config", None)
        if config:
            values = getattr(config, config_attr, None)
            if values:
                return list(values)

    # Try to load config directly (for early validation before context is set)
    try:
        from doxtr_doto.cli.config import load_config
        config = load_config()
        values = getattr(config, config_attr, None)
        if values:
            return list(values)
    except Exception:
        pass

    return defaults


def validate_priority(
    ctx: Context,
    param: Parameter,
    value: str | None,
) -> str | None:
    """Validate priority against config-defined values.

    Args:
        ctx: Click context.
        param: Click parameter.
        value: Value to validate.

    Returns:
        Validated value or None.

    Raises:
        click.BadParameter: If value is not in allowed priorities.
    """
    if value is None:
        return None

    defaults = ["low", "medium", "high", "critical"]
    allowed = _get_config_values(ctx, "priorities", defaults)

    if value not in allowed:
        raise click.BadParameter(
            f"Invalid priority '{value}'. Must be one of: {', '.join(allowed)}"
        )

    return value


def validate_status(
    ctx: Context,
    param: Parameter,
    value: str | None,
) -> str | None:
    """Validate status against config-defined values.

    Args:
        ctx: Click context.
        param: Click parameter.
        value: Value to validate.

    Returns:
        Validated value or None.

    Raises:
        click.BadParameter: If value is not in allowed statuses.
    """
    if value is None:
        return None

    defaults = ["open", "in-progress", "blocked", "done"]
    allowed = _get_config_values(ctx, "statuses", defaults)

    if value not in allowed:
        raise click.BadParameter(
            f"Invalid status '{value}'. Must be one of: {', '.join(allowed)}"
        )

    return value
