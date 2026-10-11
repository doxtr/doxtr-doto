"""doto git command — link tasks to git commits."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.sync.json_store import GitData


def _get_current_commit() -> str | None:
    """Return the current HEAD commit hash, or None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _get_current_branch() -> str | None:
    """Return the current git branch name, or None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _get_commit_message(commit_hash: str) -> str | None:
    """Return the first line of a commit message, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%s", commit_hash],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _get_commit_author(commit_hash: str) -> str | None:
    """Return the author name for a commit, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%an", commit_hash],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _get_commit_date(commit_hash: str) -> str | None:
    """Return the commit date in ISO format, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%aI", commit_hash],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


@click.command("git")
@click.argument("task_id", shell_complete=complete_task_id)
@click.option(
    "--commit",
    "-c",
    "commit_hash",
    default=None,
    help="Commit hash to link (defaults to current HEAD).",
)
@click.option("--message", "-m", default=None, help="Override commit message stored in the link.")
@click.option(
    "--branch", "-b", default=None, help="Branch name to record (defaults to current branch)."
)
@click.option("--log", "-l", "show_log", is_flag=True, help="List all commits linked to the task.")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format for --log.",
)
@click.option(
    "--remove",
    "-r",
    "remove_hash",
    default=None,
    help="Remove a specific commit link by hash prefix.",
)
@click.pass_obj
def git_cmd(
    ctx: DotoContext,
    task_id: str,
    commit_hash: str | None,
    message: str | None,
    branch: str | None,
    show_log: bool,
    fmt: str,
    remove_hash: str | None,
) -> None:
    """Link a task to a git commit.

    With no flags, links TASK_ID to the current HEAD commit.

    \b
    Examples:
      doto git TASK-001                       # link to HEAD
      doto git TASK-001 --commit abc123       # link to specific commit
      doto git TASK-001 --log                 # list linked commits
      doto git TASK-001 --remove abc123       # remove a link
    """
    store = ctx.store
    formatter = ctx.formatter

    task = store.get_task(task_id)
    if task is None:
        raise click.ClickException(f"Task '{task_id}' not found.")

    git_meta: GitData = task.get("_git", {})
    links: list[dict[str, Any]] = git_meta.get("commits", [])

    # ── list mode ──────────────────────────────────────────────────────────
    if show_log:
        if not links:
            formatter.print(f"No commits linked to {task_id}.")
            return
        if fmt == "json":
            formatter.print_json(links)
        else:
            formatter.print(f"Commits linked to {task_id}:")
            for link in links:
                branch_name = link.get("branch", "")
                # Escape brackets for Rich markup (\[ is literal bracket)
                branch_label = f"  \\[{branch_name}]" if branch_name else ""
                msg = link.get("message") or "(no message)"
                date_str = link.get("date", "")[:10] if link.get("date") else ""
                author = link.get("author", "")
                meta_parts = []
                if date_str:
                    meta_parts.append(date_str)
                if author:
                    meta_parts.append(author)
                meta_str = f"  ({', '.join(meta_parts)})" if meta_parts else ""
                formatter.print(f"  {link['hash'][:12]}  {msg}{branch_label}{meta_str}")
        return

    # ── remove mode ────────────────────────────────────────────────────────
    if remove_hash:
        before = len(links)
        links = [lk for lk in links if not lk["hash"].startswith(remove_hash)]
        if len(links) == before:
            raise click.ClickException(
                f"No link with hash prefix '{remove_hash}' found on {task_id}."
            )
        git_meta["commits"] = links
        store.update_task(task_id, {"_git": git_meta})
        store.save()
        formatter.print_success(f"Removed commit link {remove_hash} from {task_id}.")
        return

    # ── link mode (default) ────────────────────────────────────────────────
    resolved_hash = commit_hash or _get_current_commit()
    if not resolved_hash:
        raise click.ClickException(
            "Could not determine commit hash. "
            "Pass --commit HASH explicitly, or run inside a git repository."
        )

    resolved_branch = branch or _get_current_branch()
    resolved_message = message or _get_commit_message(resolved_hash)
    resolved_author = _get_commit_author(resolved_hash)
    resolved_date = _get_commit_date(resolved_hash)

    # Deduplicate: don't store the same hash twice
    existing_hashes = {lk["hash"] for lk in links}
    if resolved_hash in existing_hashes:
        formatter.print(f"Commit {resolved_hash[:12]} is already linked to {task_id}.")
        return

    entry: dict[str, Any] = {"hash": resolved_hash}
    if resolved_message:
        entry["message"] = resolved_message
    if resolved_branch:
        entry["branch"] = resolved_branch
    if resolved_author:
        entry["author"] = resolved_author
    if resolved_date:
        entry["date"] = resolved_date

    links.append(entry)
    git_meta["commits"] = links
    store.update_task(task_id, {"_git": git_meta})
    store.save()

    formatter.print_success(f"Linked commit {resolved_hash[:12]} to {task_id}.")
