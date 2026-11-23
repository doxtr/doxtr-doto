"""doto config command - Show and set current configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.date_utils import format_work_length, parse_work_length

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter


@click.command("config")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option(
    "--set-day-length",
    "day_length",
    metavar="LENGTH",
    help="Set the expected working-day length, e.g. '8h', '8.4h', '8h24m'.",
)
@click.option(
    "--set-week-length",
    "week_length",
    metavar="LENGTH",
    help="Set the expected working-week length, e.g. '40h', '37.5h'. "
    "Use 'none' to clear and derive the week target from the day length.",
)
@click.option(
    "--set-holiday-allowance",
    "holiday_allowance",
    metavar="DAYS",
    type=float,
    help="Set the yearly holiday allowance in days (half-days allowed, e.g. 25 or 27.5).",
)
@click.pass_obj
def config_cmd(
    ctx: DotoContext,
    output_format: str,
    day_length: str | None,
    week_length: str | None,
    holiday_allowance: float | None,
) -> None:
    """Show or set current doto configuration.

    Displays the active configuration including operation mode, paths,
    defaults, display settings, validation sets, and the work-clock settings
    (working-day / -week length and holiday allowance) used for overtime and
    leave tracking.

    The ``--set-*`` options persist work-clock settings to the global config
    file (the same place the work clock and breaks live):

        doto config --set-day-length 8h24m

        doto config --set-week-length 40h

        doto config --set-holiday-allowance 27.5

    Examples:

        doto config

        doto config --format json
    """
    formatter = ctx.formatter
    config = ctx.config

    if day_length is not None or week_length is not None or holiday_allowance is not None:
        _apply_work_settings(ctx, day_length, week_length, holiday_allowance)
        return

    state = ctx.global_store.load()
    week_minutes = state.week_length_minutes
    config_data = {
        "mode": config.mode.value,
        "json_file": str(config.get_json_path()),
        "json_file_exists": config.get_json_path().exists(),
        "source_dir": str(config.source_dir),
        "inbox_file": str(config.get_inbox_path()),
        "conf_py": str(config.conf_py) if config.conf_py else None,
        "defaults": {
            "priority": config.default_priority,
            "status": config.default_status,
            "assignee": config.default_assignee or "(none)",
            "id_prefix": config.id_prefix,
            "id_sequential": config.id_sequential,
        },
        "display": {
            "date_format": config.date_format,
            "color": config.color,
            "pager": config.pager,
            "editor": config.editor or "(system default)",
        },
        "validation": {
            "statuses": config.statuses,
            "priorities": config.priorities,
        },
        "work": {
            "day_length": format_work_length(state.day_length_minutes),
            "week_length": (
                format_work_length(week_minutes)
                if week_minutes is not None
                else "(derived from day length)"
            ),
            "holiday_allowance_days": state.holiday_allowance_days,
        },
    }

    if output_format == "json":
        formatter.print_json(config_data)
    else:
        _print_config_table(formatter, config_data)


def _apply_work_settings(
    ctx: DotoContext,
    day_length: str | None,
    week_length: str | None,
    holiday_allowance: float | None,
) -> None:
    """Persist the ``--set-*`` work-clock settings to the global config file.

    Validates each supplied value (work lengths via
    :func:`doxtr_doto.date_utils.parse_work_length`, the allowance as a
    non-negative number) and saves the global state. A ``week_length`` of
    ``none``/``off``/``0`` clears the weekly target so the week expectation is
    derived from the day length.

    Args:
        ctx: The CLI context.
        day_length: New working-day length string, or None to leave unchanged.
        week_length: New working-week length string (or ``none`` to clear), or
            None to leave unchanged.
        holiday_allowance: New yearly holiday allowance in days, or None.

    Raises:
        click.ClickException: On an invalid value.
    """
    formatter = ctx.formatter
    state = ctx.global_store.load()
    changes: list[str] = []

    if day_length is not None:
        try:
            minutes = parse_work_length(day_length)
        except (ValueError, TypeError) as exc:
            raise click.ClickException(f"Invalid --set-day-length: {exc}") from exc
        if not minutes:
            raise click.ClickException("Working-day length must be positive.")
        state.day_length_minutes = minutes
        changes.append(f"working day = {format_work_length(minutes)}")

    if week_length is not None:
        if week_length.strip().lower() in {"none", "off", "0", ""}:
            state.week_length_minutes = None
            changes.append("working week = (derived from day length)")
        else:
            try:
                minutes = parse_work_length(week_length)
            except (ValueError, TypeError) as exc:
                raise click.ClickException(f"Invalid --set-week-length: {exc}") from exc
            if not minutes:
                raise click.ClickException("Working-week length must be positive.")
            state.week_length_minutes = minutes
            changes.append(f"working week = {format_work_length(minutes)}")

    if holiday_allowance is not None:
        if holiday_allowance < 0:
            raise click.ClickException("Holiday allowance must not be negative.")
        state.holiday_allowance_days = float(holiday_allowance)
        changes.append(f"holiday allowance = {holiday_allowance:g} day(s)")

    ctx.global_store.save(state)
    formatter.print_success("Updated work settings: " + "; ".join(changes) + ".")


def _print_config_table(formatter: OutputFormatter, config_data: dict[str, Any]) -> None:
    """Print configuration as a formatted table."""
    formatter.print("Current doto configuration:", style="bold")
    formatter.print("")

    # Core settings
    formatter.print("Core Settings:", style="bold underline")
    formatter.print(f"  Mode:            {config_data['mode']}")
    formatter.print(f"  JSON database:   {config_data['json_file']}")
    if config_data["json_file_exists"]:
        formatter.print("                   (exists)", style="green")
    else:
        formatter.print("                   (not created yet)", style="yellow")
    formatter.print(f"  Source dir:      {config_data['source_dir']}")
    formatter.print(f"  Inbox file:      {config_data['inbox_file']}")
    if config_data["conf_py"]:
        formatter.print(f"  Sphinx conf.py:  {config_data['conf_py']}")
    formatter.print("")

    # Defaults
    formatter.print("Default Values:", style="bold underline")
    defaults = config_data["defaults"]
    formatter.print(f"  Priority:        {defaults['priority']}")
    formatter.print(f"  Status:          {defaults['status']}")
    formatter.print(f"  Assignee:        {defaults['assignee']}")
    formatter.print(f"  ID prefix:       {defaults['id_prefix']}")
    formatter.print(f"  Sequential IDs:  {defaults['id_sequential']}")
    formatter.print("")

    # Display settings
    formatter.print("Display Settings:", style="bold underline")
    display = config_data["display"]
    formatter.print(f"  Date format:     {display['date_format']}")
    formatter.print(f"  Color:           {display['color']}")
    formatter.print(f"  Pager:           {display['pager']}")
    formatter.print(f"  Editor:          {display['editor']}")
    formatter.print("")

    # Validation
    formatter.print("Validation:", style="bold underline")
    validation = config_data["validation"]
    formatter.print(f"  Statuses:        {', '.join(validation['statuses'])}")
    formatter.print(f"  Priorities:      {', '.join(validation['priorities'])}")

    # Work clock (overtime + leave tracking)
    work = config_data.get("work")
    if work:
        formatter.print("")
        formatter.print("Work Clock:", style="bold underline")
        formatter.print(f"  Working day:     {work['day_length']}")
        formatter.print(f"  Working week:    {work['week_length']}")
        formatter.print(f"  Holiday days:    {work['holiday_allowance_days']:g}")
