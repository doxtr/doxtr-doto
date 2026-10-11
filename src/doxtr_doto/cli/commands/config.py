"""doto config command - Show current configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

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
@click.pass_obj
def config_cmd(ctx: DotoContext, output_format: str) -> None:
    """Show current doto configuration.

    Displays the active configuration including:
    - Operation mode (sphinx/standalone)
    - JSON database path
    - Source directory
    - Default values for new tasks
    - Valid statuses and priorities

    Examples:

        doto config

        doto config --format json
    """
    formatter = ctx.formatter
    config = ctx.config

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
    }

    if output_format == "json":
        formatter.print_json(config_data)
    else:
        _print_config_table(formatter, config_data)


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
