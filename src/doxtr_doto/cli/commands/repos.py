"""doto repos command - manage the cached cross-repo registry.

``doto repos`` shows the cached repositories. Discovery is explicit:
``doto repos rescan [PATH]`` rediscovers and caches, while ``add``/``forget``
edit the cache directly. Normal operation reads the cache and never walks the
filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.repo_registry import RepoRegistry

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.group("repos", invoke_without_command=True)
@click.pass_context
def repos(click_ctx: click.Context) -> None:
    """Manage the cached registry of discovered doto repositories.

    A repository is any directory containing ``.doto/tasks.json``. The
    registry is cached in the global config so rediscovery only happens on
    request (``doto repos rescan``). With no subcommand, the cached
    repositories are listed.
    """
    if click_ctx.invoked_subcommand is None:
        _render_repos_list(click_ctx.obj, json_output=False)


def _render_repos_list(ctx: DotoContext, json_output: bool) -> None:
    """Render the cached repository list.

    Shared by the bare ``repos`` group and the ``repos list`` subcommand so
    both produce identical output.

    Args:
        ctx: The CLI context.
        json_output: Whether to emit JSON.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    registry = RepoRegistry(ctx.global_store)
    found = registry.list_repos()

    if formatter.json_output:
        formatter.print_json({"repositories": [r.to_dict() for r in found]})
        return

    if not found:
        formatter.print("No repositories cached. Run 'doto repos rescan' to discover them.")
        return

    formatter.print(f"{'NAME':<20} PATH")
    formatter.print("-" * 60)
    for repo in found:
        formatter.print(f"{repo.name:<20} {repo.path}")


@repos.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def repos_list(ctx: DotoContext, json_output: bool) -> None:
    """List cached repositories (no filesystem scan)."""
    _render_repos_list(ctx, json_output)


@repos.command("rescan")
@click.argument(
    "path",
    required=False,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def repos_rescan(
    ctx: DotoContext,
    path: Path | None,
    json_output: bool,
) -> None:
    """Rediscover repositories under PATH (default: cwd) and cache them."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    start = path or Path.cwd()
    registry = RepoRegistry(ctx.global_store)
    found = registry.rescan(start)

    if formatter.json_output:
        formatter.print_json({"repositories": [r.to_dict() for r in found]})
        return

    formatter.print_success(
        f"Discovered {len(found)} repositor{'y' if len(found) == 1 else 'ies'} under {start}."
    )
    for repo in found:
        formatter.print(f"  {repo.name:<20} {repo.path}")


@repos.command("add")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def repos_add(ctx: DotoContext, path: Path, json_output: bool) -> None:
    """Add a single repository PATH to the cache."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    registry = RepoRegistry(ctx.global_store)
    try:
        repo = registry.add(path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if formatter.json_output:
        formatter.print_json({"added": repo.to_dict()})
        return
    formatter.print_success(f"Added {repo.name} ({repo.path}).")


@repos.command("forget")
@click.argument("name")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def repos_forget(ctx: DotoContext, name: str, json_output: bool) -> None:
    """Remove a repository from the cache by NAME."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    registry = RepoRegistry(ctx.global_store)
    removed = registry.forget(name)

    if formatter.json_output:
        formatter.print_json({"forgotten": name, "removed": removed})
        return
    if removed:
        formatter.print_success(f"Forgot repository '{name}'.")
    else:
        formatter.print_warning(f"No cached repository named '{name}'.")
