"""doto calsync command group - sync tasks to a calendar.

Subcommands:

* ``doto calsync status``  - show config + how many tasks would sync.
* ``doto calsync login``   - run the provider's OAuth2 flow (Google/Microsoft).
* ``doto calsync logout``  - clear cached OAuth tokens.
* ``doto calsync push``    - compute and apply a push plan (``--dry-run`` to preview).
* ``doto calsync pull``    - import/reconcile calendar events into doto (``--dry-run``).
* ``doto calsync sync``    - push-only, or two-way (pull+push) when
  ``direction = "two-way"`` is configured.
* ``doto calsync conflicts`` - list tasks with an unresolved sync conflict.
* ``doto calsync resolve`` - resolve a conflict (keep local/remote/both).

Both push and pull directions are supported. All provider SDKs are optional
(the ``[calendar]`` extra) and imported lazily, so this module imports cleanly
even when they are absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.calsync.engine import (
    Action,
    PullAction,
    PullPlan,
    SyncPlan,
    apply_plan,
    apply_pull_plan,
    build_plan,
    build_pull_plan,
    local_wins_policy,
    merge_wins_policy,
    two_way_sync,
)
from doxtr_doto.calsync.state import CalSyncState
from doxtr_doto.cli.completion import complete_task_id
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
    name = auth.canonical_token_name(provider)
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
@click.option("--dry-run", "-n", is_flag=True, help="Show the plan(s) without applying.")
@click.option("--exclude-done", is_flag=True, help="Keep completed tasks off the calendar.")
@click.pass_context
def calsync_sync(click_ctx: click.Context, dry_run: bool, exclude_done: bool) -> None:
    """Sync tasks with the calendar.

    With the default ``direction = "push"`` this is push-only (doto ->
    calendar). With ``direction = "two-way"`` it runs a full two-way sync:
    pull (calendar -> doto) then push (doto -> calendar). ``--dry-run`` previews
    both directions without changing anything.
    """
    ctx: DotoContext = click_ctx.obj
    cal = ctx.config.calendar
    normalized = cal.normalized_direction()
    # Dispatch per direction so adding a mode is one table entry, not a new
    # branch. ``pull`` runs the inbound pass only; ``two-way`` runs pull+push;
    # anything else (``push``) falls through to the push-only command.
    if normalized == "two-way":
        _run_two_way(ctx, dry_run=dry_run, exclude_done=exclude_done)
        return
    if normalized == "pull":
        click_ctx.invoke(calsync_pull, dry_run=dry_run)
        return
    click_ctx.invoke(calsync_push, dry_run=dry_run, exclude_done=exclude_done)


def _print_pull_plan(fmt: OutputFormatter, plan: PullPlan) -> None:
    """Render an inbound plan to the formatter."""
    icons = {
        PullAction.IMPORT: "+",
        PullAction.UPDATE_LOCAL: "~",
        PullAction.ARCHIVE_LOCAL: "-",
        PullAction.SKIP: "=",
    }
    for item in plan.items:
        if item.action is PullAction.SKIP:
            continue
        label = item.task_id or item.remote_uid or "(new)"
        fmt.print(f"  {icons[item.action]} {label}  ({item.reason})")


@calsync.command("pull")
@click.option("--dry-run", "-n", is_flag=True, help="Show the plan without applying it.")
@click.pass_obj
def calsync_pull(ctx: DotoContext, dry_run: bool) -> None:
    """Import/reconcile calendar events into doto (one-way: calendar -> doto).

    Brand-new, user-created calendar events become new doto tasks; events doto
    created itself are left to ``push``. A previously-imported event the user
    deleted archives its local task (soft delete). Idempotent: re-running with
    no remote changes does nothing.
    """
    _require_enabled(ctx)
    cal = ctx.config.calendar
    fmt = ctx.formatter

    ctx.store.load()
    tasks = {tid: dict(task) for tid, task in ctx.store.get_all_tasks().items()}
    state = CalSyncState(_state_path(ctx))
    state.load()

    from doxtr_doto.calsync.providers import ProviderError, get_provider

    provider_cls = get_provider(cal.provider)
    provider = provider_cls(cal)
    try:
        provider.connect()
        remote_events = provider.list_events()
    except ProviderError as exc:
        raise click.ClickException(str(exc)) from exc
    except NotImplementedError as exc:
        raise click.ClickException(str(exc)) from exc

    plan = build_pull_plan(remote_events, tasks, state, cal)
    counts = plan.counts()

    if dry_run:
        fmt.print("Dry run - no changes will be made.")
        _print_pull_plan(fmt, plan)
        fmt.print(
            f"\nWould: {counts['import']} import, {counts['update_local']} update, "
            f"{counts['archive_local']} archive, {counts['skip']} unchanged"
        )
        return

    if not plan.actionable():
        fmt.print("Nothing to pull - doto is already up to date with the calendar.")
        return

    report = apply_pull_plan(plan, ctx.store, state, cal, id_prefix=ctx.config.id_prefix)
    ctx.store.save()
    state.save()

    fmt.print_success(
        f"Pulled: {report.imported} imported, {report.updated} updated, "
        f"{report.archived} archived, {report.skipped} unchanged."
    )
    for remote_uid, message in report.errors:
        fmt.print_error(f"  {remote_uid}: {message}")


def _run_two_way(ctx: DotoContext, *, dry_run: bool, exclude_done: bool) -> None:
    """Run (or preview) a two-way sync: pull then push."""
    _require_enabled(ctx)
    cal = ctx.config.calendar
    fmt = ctx.formatter
    repo_name = derive_repo_name(ctx.config)
    exclude = {"done"} if exclude_done else None

    ctx.store.load()
    state = CalSyncState(_state_path(ctx))
    state.load()

    from doxtr_doto.calsync.providers import ProviderError, get_provider

    provider_cls = get_provider(cal.provider)
    provider = provider_cls(cal)
    try:
        provider.connect()
        remote_events = provider.list_events()
    except ProviderError as exc:
        raise click.ClickException(str(exc)) from exc
    except NotImplementedError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        from doxtr_doto.calsync.engine import plan_two_way

        tasks = {tid: dict(task) for tid, task in ctx.store.get_all_tasks().items()}
        active = {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}
        pull_plan, push_plan, conflicts, remote_only_merges = plan_two_way(
            remote_events,
            tasks,
            active,
            state,
            cal,
            repo_name=repo_name,
            exclude_statuses=exclude,
        )
        pc = pull_plan.counts()
        sc = push_plan.counts()
        merging = cal.normalized_conflict_policy() == "merge"
        fmt.print("Dry run - no changes will be made.")
        fmt.print("Pull (calendar -> doto):")
        _print_pull_plan(fmt, pull_plan)
        fmt.print("Push (doto -> calendar):")
        _print_plan(fmt, push_plan)
        if conflicts:
            if merging:
                fmt.print(
                    "Conflicts (local + remote both changed; will be "
                    "three-way merged): " + ", ".join(conflicts)
                )
            else:
                fmt.print(
                    "Conflicts (local + remote both changed; resolved local-wins): "
                    + ", ".join(conflicts)
                )
        # Remote-only edits of doto-owned items are reconciled only under the
        # merge policy; under local-wins they are overwritten by push and not
        # worth a preview line. Surface them so the dry-run is not misleading.
        if remote_only_merges and merging:
            fmt.print(
                "Remote-only edits (will be merged back into the task): "
                + ", ".join(remote_only_merges)
            )
        fmt.print(
            f"\nWould pull: {pc['import']} import, {pc['update_local']} update, "
            f"{pc['archive_local']} archive. "
            f"Would push: {sc['create']} create, {sc['update']} update, "
            f"{sc['delete']} delete."
        )
        return

    tasks = {tid: dict(task) for tid, task in ctx.store.get_all_tasks().items()}

    def _reload_active() -> dict[str, Any]:
        return {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}

    report = two_way_sync(
        provider,
        ctx.store,
        tasks,
        state,
        cal,
        repo_name=repo_name,
        exclude_statuses=exclude,
        id_prefix=ctx.config.id_prefix,
        reload_tasks=_reload_active,
        conflict_policy=(
            merge_wins_policy if cal.normalized_conflict_policy() == "merge" else local_wins_policy
        ),
    )
    ctx.store.save()
    state.save()

    fmt.print_success(
        f"Pulled: {report.pull.imported} imported, {report.pull.updated} updated, "
        f"{report.pull.archived} archived. "
        f"Pushed: {report.push.created} created, {report.push.updated} updated, "
        f"{report.push.deleted} deleted."
    )
    if report.merged:
        fmt.print("Merged (local + remote both changed): " + ", ".join(report.merged))
        if report.merge_conflicts:
            fmt.print(
                "  Merge conflicts to resolve by hand (<<<<<<< markers in the "
                "task body): " + ", ".join(report.merge_conflicts)
            )
            fmt.print("  Find them anytime with: doto list --conflicts")
            fmt.print("  Resolve with: doto calsync resolve <id> --local|--remote|--both")
    elif report.conflicts:
        fmt.print(
            "Conflicts (local + remote both changed; resolved local-wins): "
            + ", ".join(report.conflicts)
        )
    for ident, message in [*report.pull.errors, *report.push.errors]:
        fmt.print_error(f"  {ident}: {message}")


def _summarize(value: str, width: int = 50) -> str:
    """Return a one-line, width-capped preview of a (possibly multi-line) value."""
    one_line = " ".join(str(value).split())
    if len(one_line) > width:
        return one_line[: width - 1] + "\u2026"
    return one_line or "(empty)"


@calsync.command("conflicts")
@click.pass_obj
def calsync_conflicts(ctx: DotoContext) -> None:
    """List tasks with an unresolved calendar-sync conflict.

    A two-way merge (``conflict_policy = "merge"``) flags a task when the same
    field changed on both sides. This shows each flagged task and the fields in
    conflict so you can resolve them with ``doto calsync resolve``.
    """
    from doxtr_doto.calsync.resolve import conflict_fields, conflict_preview

    ctx.store.load()
    fmt = ctx.formatter
    found = False
    for task_id, task in ctx.store.get_all_tasks().items():
        fields = conflict_fields(dict(task))
        if not fields:
            continue
        found = True
        names = ", ".join(str(f.get("field")) for f in fields)
        fmt.print(f"{task_id}  ({names})")
        for rec in fields:
            local_prev, remote_prev = conflict_preview(rec)
            fmt.print(f"    {rec.get('field')}:")
            fmt.print(f"      local : {_summarize(local_prev)}")
            fmt.print(f"      remote: {_summarize(remote_prev)}")
    if not found:
        fmt.print("No unresolved calendar-sync conflicts.")


@calsync.command("resolve")
@click.argument("task_id", shell_complete=complete_task_id)
@click.option("--local", "choice", flag_value="local", help="Keep the local value.")
@click.option("--remote", "choice", flag_value="remote", help="Keep the calendar value.")
@click.option(
    "--both",
    "choice",
    flag_value="both",
    help="Keep both (diff3-merged body / joined scalar).",
)
@click.option("--field", "-f", help="Resolve only this field (default: all).")
@click.pass_obj
def calsync_resolve(ctx: DotoContext, task_id: str, choice: str | None, field: str | None) -> None:
    """Resolve a task's calendar-sync conflict (keep local / remote / both).

    Picks the winning value for each conflicted field from the saved
    base/local/remote candidates, writes it to the task, and clears the
    conflict flag. The next ``doto calsync sync`` re-pushes the resolved value
    so the calendar converges. Pass ``--field`` to resolve one field at a time.
    """
    from doxtr_doto.calsync.resolve import (
        ResolutionChoice,
        conflict_fields,
        resolve_conflict,
    )

    if choice is None:
        raise click.UsageError("Choose one of --local, --remote, or --both.")

    ctx.store.load()
    fmt = ctx.formatter
    task = ctx.store.get_task(task_id)
    if task is None:
        raise click.ClickException(f"Task {task_id!r} not found.")
    task_dict = dict(task)
    if not conflict_fields(task_dict):
        raise click.ClickException(f"Task {task_id!r} has no unresolved calendar-sync conflict.")

    try:
        updates = resolve_conflict(task_dict, ResolutionChoice(choice), field=field)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    ctx.store.update_task(task_id, updates)
    ctx.store.save()

    resolved = ", ".join(k for k in updates if k not in ("sync_conflict", "_sync"))
    still_open = bool(updates.get("sync_conflict"))
    suffix = " (other fields still in conflict)" if still_open else ""
    fmt.print_success(f"Resolved {task_id} [{resolved}] -> kept {choice}.{suffix}")
