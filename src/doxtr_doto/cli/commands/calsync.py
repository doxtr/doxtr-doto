"""doto calsync command group - sync tasks to a calendar.

Subcommands:

* ``doto calsync status``  - show config + how many tasks would sync.
* ``doto calsync login``   - run the provider's OAuth2 flow (Google/Microsoft).
* ``doto calsync logout``  - clear cached OAuth tokens.
* ``doto calsync push``    - compute and apply a push plan (``--dry-run`` to preview).
* ``doto calsync sync``    - alias for ``push`` (push-first; two-way is future work).

Only the push direction is implemented today. All provider SDKs are optional
(the ``[calendar]`` extra) and imported lazily, so this module imports cleanly
even when they are absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.calsync.engine import Action, SyncPlan, apply_plan, build_plan
from doxtr_doto.calsync.state import CalSyncState
from doxtr_doto.cli.session import derive_repo_name

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter


def _state_path(ctx: DotoContext) -> Path:
    """Return the ``.doto/calsync.json`` path alongside the task store."""
    json_path = ctx.config.get_json_path()
    return json_path.parent / "calsync.json"


def _load_active_tasks(ctx: DotoContext) -> dict[str, dict[str, Any]]:
    """Load the active (non-archived) tasks as a plain dict."""
    ctx.store.load()
    return {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}


def _require_enabled(ctx: DotoContext) -> None:
    """Raise a Click error if calendar sync is not configured or is invalid."""
    cal = ctx.config.calendar
    if not cal.provider:
        raise click.ClickException(
            "Calendar sync is not configured. Add a [calendar] section to "
            ".doto.toml with at least 'provider' (google/microsoft/apple/caldav)."
        )
    problems = cal.validate()
    if problems:
        raise click.ClickException("Invalid [calendar] config:\n  - " + "\n  - ".join(problems))


@click.group("calsync")
def calsync() -> None:
    """Sync tasks with a calendar (Google, Microsoft, Apple, CalDAV)."""


@calsync.command("status")
@click.pass_obj
def calsync_status(ctx: DotoContext) -> None:
    """Show calendar-sync configuration and a dry-run summary."""
    cal = ctx.config.calendar
    fmt = ctx.formatter
    fmt.print(f"Enabled:    {cal.enabled}")
    fmt.print(f"Provider:   {cal.provider or '(unset)'}")
    fmt.print(f"Calendar:   {cal.calendar or '(default)'}")
    fmt.print(f"Event mode: {cal.event_mode}")
    fmt.print(f"Direction:  {cal.direction}")
    fmt.print(
        f"Workday:    {cal.workday_start}-{cal.workday_end} "
        f"(break {cal.break_start}-{cal.break_end}), "
        f"event {cal.event_duration_minutes}min"
    )
    if not cal.provider:
        return

    tasks = _load_active_tasks(ctx)
    state = CalSyncState(_state_path(ctx))
    state.load()
    plan = build_plan(tasks, state, cal, repo_name=derive_repo_name(ctx.config))
    counts = plan.counts()
    fmt.print("")
    fmt.print(
        f"Plan: {counts['create']} create, {counts['update']} update, "
        f"{counts['delete']} delete, {counts['skip']} unchanged"
    )


@calsync.command("login")
@click.pass_obj
def calsync_login(ctx: DotoContext) -> None:
    """Authenticate with the configured provider (OAuth2 browser flow)."""
    _require_enabled(ctx)
    cal = ctx.config.calendar
    from doxtr_doto.calsync.providers import ProviderError, get_provider

    provider_cls = get_provider(cal.provider)
    provider = provider_cls(cal)
    login = getattr(provider, "login", None)
    if login is None:
        # CalDAV/Apple use username+password; no interactive login needed.
        try:
            provider.connect()
        except ProviderError as exc:
            raise click.ClickException(str(exc)) from exc
        ctx.formatter.print_success(
            f"{cal.provider}: credentials OK (CalDAV uses username/password)."
        )
        return
    try:
        login()
    except ProviderError as exc:
        raise click.ClickException(str(exc)) from exc
    ctx.formatter.print_success(f"Logged in to {cal.provider}.")


@calsync.command("logout")
@click.pass_obj
def calsync_logout(ctx: DotoContext) -> None:
    """Clear cached OAuth tokens for the configured provider."""
    _require_enabled(ctx)
    from doxtr_doto.calsync import auth

    provider = ctx.config.calendar.provider
    # Normalize apple/icloud/outlook aliases to the stored token name.
    name = {
        "apple": "caldav",
        "icloud": "caldav",
        "outlook": "microsoft",
        "ms": "microsoft",
        "graph": "microsoft",
    }.get(provider, provider)
    removed = auth.clear_token(name)
    if removed:
        ctx.formatter.print_success(f"Cleared cached token for {provider}.")
    else:
        ctx.formatter.print(f"No cached token for {provider}.")


def _print_plan(fmt: OutputFormatter, plan: SyncPlan) -> None:
    """Render a plan to the formatter."""
    icons = {
        Action.CREATE: "+",
        Action.UPDATE: "~",
        Action.DELETE: "-",
        Action.SKIP: "=",
    }
    for item in plan.items:
        if item.action is Action.SKIP:
            continue
        fmt.print(f"  {icons[item.action]} {item.task_id}  ({item.reason})")


@calsync.command("push")
@click.option("--dry-run", "-n", is_flag=True, help="Show the plan without applying it.")
@click.option(
    "--exclude-done",
    is_flag=True,
    help="Keep completed tasks off the calendar (and remove previously-synced ones).",
)
@click.pass_obj
def calsync_push(ctx: DotoContext, dry_run: bool, exclude_done: bool) -> None:
    """Push tasks to the configured calendar (one-way: doto -> calendar)."""
    _require_enabled(ctx)
    cal = ctx.config.calendar
    fmt = ctx.formatter

    tasks = _load_active_tasks(ctx)
    state = CalSyncState(_state_path(ctx))
    state.load()
    exclude = {"done"} if exclude_done else None
    plan = build_plan(
        tasks,
        state,
        cal,
        repo_name=derive_repo_name(ctx.config),
        exclude_statuses=exclude,
    )
    counts = plan.counts()

    if dry_run:
        fmt.print("Dry run - no changes will be made.")
        _print_plan(fmt, plan)
        fmt.print(
            f"\nWould: {counts['create']} create, {counts['update']} update, "
            f"{counts['delete']} delete, {counts['skip']} unchanged"
        )
        return

    if not plan.actionable():
        fmt.print("Nothing to sync - calendar is already up to date.")
        return

    from doxtr_doto.calsync.providers import ProviderError, get_provider

    provider_cls = get_provider(cal.provider)
    provider = provider_cls(cal)
    try:
        provider.connect()
    except ProviderError as exc:
        raise click.ClickException(str(exc)) from exc

    report = apply_plan(plan, provider, state, cal)
    state.save()

    fmt.print_success(
        f"Synced: {report.created} created, {report.updated} updated, "
        f"{report.deleted} deleted, {report.skipped} unchanged."
    )
    for task_id, message in report.errors:
        fmt.print_error(f"  {task_id}: {message}")


@calsync.command("sync")
@click.option("--dry-run", "-n", is_flag=True, help="Show the plan without applying it.")
@click.option("--exclude-done", is_flag=True, help="Keep completed tasks off the calendar.")
@click.pass_context
def calsync_sync(click_ctx: click.Context, dry_run: bool, exclude_done: bool) -> None:
    """Sync tasks with the calendar (push-first; alias for 'push')."""
    click_ctx.invoke(calsync_push, dry_run=dry_run, exclude_done=exclude_done)
