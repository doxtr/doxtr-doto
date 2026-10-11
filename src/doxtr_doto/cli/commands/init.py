"""doto init command - Initialize doto in a project."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


DEFAULT_DOTO_TOML = """\
[doto]
# Source directory (relative to this file)
# source_dir = "."

# JSON task store location
json_file = ".doto/tasks.json"

# Inbox file for new/reopened tasks
inbox_file = "tasks/inbox.rst"

# ID generation
id_prefix = "DOTO"
id_sequential = true

# Defaults for new tasks
default_priority = "medium"
default_status = "open"
# default_assignee = ""

# Display settings
date_format = "%Y-%m-%d"
color = "auto"

# Valid values
statuses = ["open", "in-progress", "blocked", "done"]
priorities = ["low", "medium", "high", "critical"]
"""


DEFAULT_USER_CONFIG = """\
[doto]
# Default storage location for standalone mode
json_file = "~/.doto/tasks.json"

# Personal defaults
default_priority = "medium"
default_status = "open"
# default_assignee = "me"

# ID generation
id_prefix = "TODO"
id_sequential = true

# Display settings
date_format = "%Y-%m-%d"
color = "auto"
# editor = ""  # Falls back to $EDITOR

# Valid values
statuses = ["open", "in-progress", "blocked", "done"]
priorities = ["low", "medium", "high", "critical"]
"""


DEFAULT_INBOX_RST = """\
Task Inbox
==========

This file serves as the inbox for new tasks created via the CLI
and for reopened archived tasks.

Tasks will be placed here automatically when:
- A new task is added via ``doto add`` without specifying a file
- An archived task is reopened and its original file no longer exists

You can move tasks to other files by cutting and pasting the
``.. doto::`` directives.

"""


@click.command("init")
@click.option(
    "--source",
    "-s",
    "source_dir",
    type=click.Path(path_type=Path),
    help="Sphinx source directory.",
)
@click.option(
    "--inbox",
    "-i",
    "inbox_file",
    type=click.Path(path_type=Path),
    help="Inbox file for new tasks.",
)
@click.option(
    "--standalone",
    is_flag=True,
    help="Initialize standalone mode (~/.doto/).",
)
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files.")
@click.pass_obj
def init(
    ctx: DotoContext,
    source_dir: Path | None,
    inbox_file: Path | None,
    standalone: bool,
    force: bool,
) -> None:
    """Initialize doto in a project.

    Creates the necessary configuration files and directories:
    - .doto.toml (project configuration)
    - .doto/tasks.json (task store)
    - Inbox file for new tasks

    Use --standalone to initialize personal task management in ~/.doto/.
    """
    formatter = ctx.formatter

    if standalone:
        # Initialize standalone mode in ~/.doto/
        doto_dir = Path.home() / ".doto"
        config_file = doto_dir / "config.toml"
        json_file = doto_dir / "tasks.json"

        # Check for existing files
        if config_file.exists() and not force:
            raise click.ClickException(f"{config_file} already exists. Use --force to overwrite.")

        # Create directory
        doto_dir.mkdir(parents=True, exist_ok=True)

        # Write config
        config_file.write_text(DEFAULT_USER_CONFIG)
        formatter.print_success(f"Created {config_file}")

        # Create empty JSON store
        if not json_file.exists() or force:
            json_file.write_text('{\n  "version": 2,\n  "tasks": {}\n}\n')
            formatter.print_success(f"Created {json_file}")

        formatter.print("\nStandalone mode initialized.")
        formatter.print("Use 'doto add' to create your first task.")
        formatter.print("\nTo enable tab completion, run:")
        formatter.print("  doto completion --install")
        return

    # Initialize Sphinx project mode
    project_dir = Path.cwd()
    if source_dir:
        project_dir = source_dir.resolve()

    # Determine paths
    doto_toml = project_dir / ".doto.toml"
    doto_dir = project_dir / ".doto"
    json_file = doto_dir / "tasks.json"

    if inbox_file:
        inbox_path = project_dir / inbox_file
    else:
        inbox_path = project_dir / "tasks" / "inbox.rst"

    # Check for existing files
    if doto_toml.exists() and not force:
        raise click.ClickException(f"{doto_toml} already exists. Use --force to overwrite.")

    # Create .doto directory
    doto_dir.mkdir(parents=True, exist_ok=True)

    # Write .doto.toml
    doto_toml.write_text(DEFAULT_DOTO_TOML)
    formatter.print_success(f"Created {doto_toml}")

    # Create empty JSON store
    if not json_file.exists() or force:
        json_file.write_text('{\n  "version": 2,\n  "tasks": {}\n}\n')
        formatter.print_success(f"Created {json_file}")

    # Create inbox file
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    if not inbox_path.exists() or force:
        inbox_path.write_text(DEFAULT_INBOX_RST)
        formatter.print_success(f"Created {inbox_path}")

    # Check for conf.py
    conf_py = project_dir / "conf.py"
    if not conf_py.exists():
        # Check common locations
        for candidate in ["source/conf.py", "docs/conf.py", "docs/source/conf.py"]:
            candidate_path = project_dir / candidate
            if candidate_path.exists():
                conf_py = candidate_path
                break

    if conf_py.exists():
        formatter.print(f"\nFound Sphinx config at {conf_py}")
        formatter.print("Add 'doto' to your extensions list:")
        formatter.print("  extensions = ['doto', ...]")
    else:
        formatter.print("\nNo conf.py found. Create a Sphinx project or use --standalone.")

    formatter.print("\nProject initialized. Use 'doto add' to create your first task.")
    formatter.print("\nTo enable tab completion, run:")
    formatter.print("  doto completion --install")
