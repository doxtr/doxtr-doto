"""doto completion command - Install shell tab completion."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def detect_shell() -> str | None:
    """Detect the current shell.

    Returns:
        Shell name ('bash', 'zsh', 'fish') or None if unknown.
    """
    # Check SHELL environment variable
    shell_path = os.environ.get("SHELL", "")
    shell_name = Path(shell_path).name if shell_path else ""

    if shell_name in ("bash", "zsh", "fish"):
        return shell_name

    # Try to detect from parent process on Linux/macOS
    try:
        ppid = os.getppid()
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "comm="],
            capture_output=True,
            text=True,
        )
        parent = result.stdout.strip().lstrip("-")
        if parent in ("bash", "zsh", "fish"):
            return parent
    except Exception:
        pass

    return None


def get_completion_script(shell: str) -> str:
    """Get the completion script for a shell.

    Args:
        shell: Shell name ('bash', 'zsh', 'fish').

    Returns:
        Completion script content.
    """
    env_var = f"_DOTO_COMPLETE={shell}_source"
    result = subprocess.run(
        ["doto"],
        capture_output=True,
        text=True,
        env={**os.environ, "_DOTO_COMPLETE": f"{shell}_source"},
    )
    return result.stdout


def get_rc_file(shell: str) -> Path:
    """Get the RC file path for a shell.

    Args:
        shell: Shell name.

    Returns:
        Path to the RC file.
    """
    home = Path.home()
    if shell == "bash":
        # Prefer .bashrc, fall back to .bash_profile on macOS
        bashrc = home / ".bashrc"
        if bashrc.exists():
            return bashrc
        return home / ".bash_profile"
    elif shell == "zsh":
        return home / ".zshrc"
    elif shell == "fish":
        # Fish uses a config directory
        return home / ".config" / "fish" / "completions" / "doto.fish"
    return home / ".bashrc"


def get_eval_line(shell: str) -> str:
    """Get the eval line to add to RC file.

    Args:
        shell: Shell name.

    Returns:
        Line to add to RC file.
    """
    if shell == "fish":
        return "_DOTO_COMPLETE=fish_source doto | source"
    else:
        return f'eval "$(_DOTO_COMPLETE={shell}_source doto)"'


@click.command("completion")
@click.argument("shell", required=False, type=click.Choice(["bash", "zsh", "fish"]))
@click.option("--install", "-i", is_flag=True, help="Install completion to shell RC file.")
@click.option("--stdout", "-s", is_flag=True, help="Print completion script to stdout.")
@click.pass_obj
def completion(
    ctx: DotoContext,
    shell: str | None,
    install: bool,
    stdout: bool,
) -> None:
    """Set up shell tab completion.

    Detects your shell automatically, or specify one explicitly.

    To enable completion for the current session:

        eval "$(doto completion bash)"

    To install permanently:

        doto completion --install

    Supported shells: bash, zsh, fish
    """
    formatter = ctx.formatter

    # Auto-detect shell if not specified
    if not shell:
        shell = detect_shell()
        if not shell:
            raise click.ClickException(
                "Could not detect shell. Please specify: doto completion bash|zsh|fish"
            )
        formatter.print(f"Detected shell: {shell}")

    # Print to stdout (for eval)
    if stdout or (not install and not stdout):
        if not install:
            # Default behavior: print script for eval
            script = get_completion_script(shell)
            click.echo(script, nl=False)
            return

    # Install to RC file
    if install:
        eval_line = get_eval_line(shell)
        rc_file = get_rc_file(shell)

        # Fish uses a separate completions file
        if shell == "fish":
            rc_file.parent.mkdir(parents=True, exist_ok=True)
            script = get_completion_script(shell)
            rc_file.write_text(script)
            formatter.print_success(f"Installed completion to {rc_file}")
            formatter.print("Completion is now active in new fish shells.")
            return

        # Check if already installed
        if rc_file.exists():
            content = rc_file.read_text()
            if "_DOTO_COMPLETE" in content:
                formatter.print_warning(f"Completion already installed in {rc_file}")
                return

        # Append to RC file
        with open(rc_file, "a") as f:
            f.write(f"\n# doto shell completion\n{eval_line}\n")

        formatter.print_success(f"Added completion to {rc_file}")
        formatter.print(f"\nTo activate now, run:\n  source {rc_file}")
        formatter.print("Or start a new shell session.")
