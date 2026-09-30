"""Main CLI entry point for doto."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from doxtr_doto.cli.config import DotoConfig, OperationMode, load_config
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.output import OutputFormatter, get_formatter


class DotoContext:
    """Context object passed to all commands."""

    def __init__(
        self,
        config: DotoConfig,
        store: JsonTaskStore,
        formatter: OutputFormatter,
    ) -> None:
        self.config = config
        self.store = store
        self.formatter = formatter


pass_context = click.make_pass_decorator(DotoContext)


@click.group()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    help="Path to Sphinx project or .doto.toml config file.",
)
@click.option(
    "--json",
    "-j",
    "json_path",
    type=click.Path(exists=False, path_type=Path),
    help="Path to tasks.json file (overrides config).",
)
@click.option(
    "--color",
    type=click.Choice(["auto", "always", "never"]),
    default="auto",
    help="Color output mode.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress non-essential output.",
)
@click.version_option(package_name="doxtr-doto")
@click.pass_context
def cli(
    ctx: click.Context,
    config_path: Path | None,
    json_path: Path | None,
    color: str,
    quiet: bool,
) -> None:
    """doto - Documentation task management CLI.

    Manage documentation tasks from the command line. Works with Sphinx
    projects (bidirectional sync with RST files) or standalone mode.
    """
    # Load configuration
    cli_overrides = {"color": color} if color != "auto" else {}
    config = load_config(
        config_path=config_path,
        json_path=json_path,
        cli_overrides=cli_overrides,
    )

    # Create JSON store
    store = JsonTaskStore(config.get_json_path())

    # Create formatter
    formatter = get_formatter(config, quiet=quiet)

    # Store in context
    ctx.obj = DotoContext(config=config, store=store, formatter=formatter)


# Import and register commands
from doxtr_doto.cli.commands.add import add
from doxtr_doto.cli.commands.archive import archive
from doxtr_doto.cli.commands.config import config_cmd
from doxtr_doto.cli.commands.delete import delete
from doxtr_doto.cli.commands.deps import deps
from doxtr_doto.cli.commands.export import export
from doxtr_doto.cli.commands.list import list_tasks
from doxtr_doto.cli.commands.search import search
from doxtr_doto.cli.commands.show import show
from doxtr_doto.cli.commands.update import update
from doxtr_doto.cli.commands.done import done
from doxtr_doto.cli.commands.reopen import reopen
from doxtr_doto.cli.commands.resolve import resolve
from doxtr_doto.cli.commands.init import init
from doxtr_doto.cli.commands.stats import stats
from doxtr_doto.cli.commands.completion import completion
from doxtr_doto.cli.commands.next import next_task
from doxtr_doto.cli.commands.tree import tree
from doxtr_doto.cli.commands.series import series
from doxtr_doto.cli.commands.git import git_cmd

cli.add_command(add)
cli.add_command(archive)
cli.add_command(config_cmd, name="config")
cli.add_command(completion)
cli.add_command(delete)
cli.add_command(deps)
cli.add_command(done)
cli.add_command(export)
cli.add_command(init)
cli.add_command(list_tasks, name="list")
cli.add_command(next_task, name="next")
cli.add_command(reopen)
cli.add_command(resolve)
cli.add_command(search)
cli.add_command(series)
cli.add_command(show)
cli.add_command(stats)
cli.add_command(tree)
cli.add_command(update)
cli.add_command(git_cmd, name="git")


def main() -> None:
    """Main entry point."""
    try:
        cli()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
