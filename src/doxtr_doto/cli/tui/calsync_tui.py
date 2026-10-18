"""Calendar-sync orchestration for the TUI ``C`` (Calendar Sync) domain.

The TUI's ``C`` prefix exposes the same operations as the ``doto calsync``
command group (status / push / pull / sync / login / logout) but drives them
through small, Textual-free functions that return a plain
:class:`CalSyncOutcome` the app can render in a notification. Keeping the
orchestration here (rather than inline in :mod:`doxtr_doto.cli.tui.app`) means
it is unit-testable without a running Textual app and without duplicating the
engine wiring already used by :mod:`doxtr_doto.cli.commands.calsync`.

All network/auth work (provider ``connect`` / ``list_events`` / push) is
blocking, so the app calls these from a Textual thread worker; the functions
here are deliberately synchronous and side-effect-contained (they load the
task store and sync state, apply the plan, and persist both), returning a
summary string plus a success flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from doxtr_doto.calsync.engine import (
    apply_plan,
    apply_pull_plan,
    build_plan,
    build_pull_plan,
    local_wins_policy,
    merge_wins_policy,
    two_way_sync,
)
from doxtr_doto.calsync.state import CalSyncState
from doxtr_doto.cli.session import derive_repo_name

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@dataclass(slots=True)
class CalSyncOutcome:
    """Result of a TUI calendar-sync operation.

    Mirrors the subsystem's other result/report types (``PushResult``,
    ``SyncReport``, ``PullReport``, ``TwoWayReport``) by being a dataclass
    rather than a hand-rolled class.

    Attributes:
        ok: Whether the operation completed without a fatal/config error.
            Per-item provider errors still set ``ok`` True (the run itself
            succeeded); they are appended to ``message`` so the user sees them.
        title: Short notification title (e.g. ``"Calendar sync"``).
        message: Human-readable summary (counts and any per-item errors).
    """

    ok: bool
    title: str
    message: str


def _state_path(ctx: DotoContext) -> Path:
    """Return the ``.doto/calsync.json`` path alongside the task store."""
    return ctx.config.get_json_path().parent / "calsync.json"


def _config_problem(ctx: DotoContext) -> str | None:
    """Return a config error string, or None when calendar sync is usable."""
    cal = ctx.config.calendar
    if not cal.provider:
        return (
            "Calendar sync is not configured. Add a [calendar] section to "
            ".doto.toml with at least 'provider'."
        )
    problems = cal.validate()
    if problems:
        return "Invalid [calendar] config: " + "; ".join(problems)
    return None


def _connect(ctx: DotoContext) -> Any:
    """Build and connect the configured provider (may raise ProviderError)."""
    from doxtr_doto.calsync.providers import get_provider

    provider_cls = get_provider(ctx.config.calendar.provider)
    provider = provider_cls(ctx.config.calendar)
    provider.connect()
    return provider


def status(ctx: DotoContext) -> CalSyncOutcome:
    """Summarize config + a dry-run plan without touching the calendar.

    Mirrors ``doto calsync status``: no network beyond what ``build_plan``
    needs (which is none -- it is computed from the local store and state), so
    this is cheap and safe to call synchronously.
    """
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar sync", problem)

    cal = ctx.config.calendar
    ctx.store.load()
    tasks = {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}
    state = CalSyncState(_state_path(ctx))
    state.load()
    plan = build_plan(tasks, state, cal, repo_name=derive_repo_name(ctx.config))
    counts = plan.counts()
    msg = (
        f"{cal.provider} / {cal.calendar or 'default'} ({cal.direction}). "
        f"Plan: {counts['create']} create, {counts['update']} update, "
        f"{counts['delete']} delete, {counts['skip']} unchanged."
    )
    return CalSyncOutcome(True, "Calendar sync", msg)


def login(ctx: DotoContext) -> CalSyncOutcome:
    """Run the provider's interactive login (OAuth browser flow)."""
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar login", problem)

    from doxtr_doto.calsync.providers import ProviderError, get_provider

    cal = ctx.config.calendar
    provider = get_provider(cal.provider)(cal)
    login_fn = getattr(provider, "login", None)
    try:
        if login_fn is None:
            # CalDAV/Apple use username+password; connect() validates them.
            provider.connect()
            return CalSyncOutcome(
                True, "Calendar login", f"{cal.provider}: credentials OK (username/password)."
            )
        login_fn()
    except ProviderError as exc:
        return CalSyncOutcome(False, "Calendar login", str(exc))
    return CalSyncOutcome(True, "Calendar login", f"Logged in to {cal.provider}.")


def logout(ctx: DotoContext) -> CalSyncOutcome:
    """Clear the cached OAuth token for the configured provider."""
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar logout", problem)

    from doxtr_doto.calsync import auth

    provider = ctx.config.calendar.provider
    # Normalize apple/icloud/outlook aliases to the stored token name (shared
    # with the CLI's ``doto calsync logout`` so the alias map cannot drift).
    name = auth.canonical_token_name(provider)
    removed = auth.clear_token(name)
    if removed:
        return CalSyncOutcome(True, "Calendar logout", f"Cleared cached token for {provider}.")
    return CalSyncOutcome(True, "Calendar logout", f"No cached token for {provider}.")


def push(ctx: DotoContext, *, exclude_done: bool = False) -> CalSyncOutcome:
    """Push tasks to the calendar (one-way doto -> calendar).

    ``exclude_done`` mirrors the CLI ``--exclude-done`` flag; it is accepted for
    parity and future use (no ``C`` sub-key toggles it yet), so a later
    "exclude done" key needs no signature change.
    """
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar push", problem)

    from doxtr_doto.calsync.providers import ProviderError

    cal = ctx.config.calendar
    ctx.store.load()
    tasks = {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}
    state = CalSyncState(_state_path(ctx))
    state.load()
    exclude = {"done"} if exclude_done else None
    plan = build_plan(
        tasks, state, cal, repo_name=derive_repo_name(ctx.config), exclude_statuses=exclude
    )
    if not plan.actionable():
        return CalSyncOutcome(True, "Calendar push", "Already up to date - nothing to push.")

    try:
        provider = _connect(ctx)
    except ProviderError as exc:
        return CalSyncOutcome(False, "Calendar push", str(exc))

    report = apply_plan(plan, provider, state, cal)
    state.save()
    msg = (
        f"Pushed: {report.created} created, {report.updated} updated, "
        f"{report.deleted} deleted, {report.skipped} unchanged."
    )
    msg += _format_errors(report.errors)
    return CalSyncOutcome(True, "Calendar push", msg)


def pull(ctx: DotoContext) -> CalSyncOutcome:
    """Import/reconcile calendar events into doto (one-way calendar -> doto)."""
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar pull", problem)

    from doxtr_doto.calsync.providers import ProviderError

    cal = ctx.config.calendar
    ctx.store.load()
    tasks = {tid: dict(task) for tid, task in ctx.store.get_all_tasks().items()}
    state = CalSyncState(_state_path(ctx))
    state.load()

    try:
        provider = _connect(ctx)
        remote_events = provider.list_events()
    except (ProviderError, NotImplementedError) as exc:
        return CalSyncOutcome(False, "Calendar pull", str(exc))

    plan = build_pull_plan(remote_events, tasks, state, cal)
    if not plan.actionable():
        return CalSyncOutcome(True, "Calendar pull", "Already up to date - nothing to pull.")

    report = apply_pull_plan(plan, ctx.store, state, cal, id_prefix=ctx.config.id_prefix)
    ctx.store.save()
    state.save()
    msg = (
        f"Pulled: {report.imported} imported, {report.updated} updated, "
        f"{report.archived} archived, {report.skipped} unchanged."
    )
    msg += _format_errors(report.errors)
    return CalSyncOutcome(True, "Calendar pull", msg)


def sync(ctx: DotoContext, *, exclude_done: bool = False) -> CalSyncOutcome:
    """Sync per the configured direction (push / pull / two-way).

    Dispatches exactly like ``doto calsync sync``: ``push`` and ``pull`` run
    the one-way helpers; ``two-way`` runs a full pull-then-push via
    :func:`doxtr_doto.calsync.engine.two_way_sync`. ``exclude_done`` mirrors the
    CLI flag and is accepted for parity / future use (no ``C`` key toggles it
    yet).
    """
    problem = _config_problem(ctx)
    if problem is not None:
        return CalSyncOutcome(False, "Calendar sync", problem)

    direction = ctx.config.calendar.normalized_direction()
    if direction == "pull":
        return pull(ctx)
    if direction != "two-way":
        return push(ctx, exclude_done=exclude_done)

    # Two-way: pull then push.
    from doxtr_doto.calsync.providers import ProviderError

    cal = ctx.config.calendar
    ctx.store.load()
    state = CalSyncState(_state_path(ctx))
    state.load()

    try:
        provider = _connect(ctx)
    except ProviderError as exc:
        return CalSyncOutcome(False, "Calendar sync", str(exc))

    tasks = {tid: dict(task) for tid, task in ctx.store.get_all_tasks().items()}

    def _reload_active() -> dict[str, Any]:
        return {tid: dict(task) for tid, task in ctx.store.iter_active_tasks()}

    exclude = {"done"} if exclude_done else None
    policy = merge_wins_policy if cal.normalized_conflict_policy() == "merge" else local_wins_policy
    report = two_way_sync(
        provider,
        ctx.store,
        tasks,
        state,
        cal,
        repo_name=derive_repo_name(ctx.config),
        exclude_statuses=exclude,
        id_prefix=ctx.config.id_prefix,
        reload_tasks=_reload_active,
        conflict_policy=policy,
    )
    ctx.store.save()
    state.save()
    msg = (
        f"Pulled: {report.pull.imported} imported, {report.pull.updated} updated, "
        f"{report.pull.archived} archived. "
        f"Pushed: {report.push.created} created, {report.push.updated} updated, "
        f"{report.push.deleted} deleted."
    )
    if report.merged:
        msg += " Merged: " + ", ".join(report.merged) + "."
        if report.merge_conflicts:
            msg += (
                " Merge conflicts (resolve the <<<<<<< markers): "
                + ", ".join(report.merge_conflicts)
                + "."
            )
    elif report.conflicts:
        msg += " Conflicts (local-wins): " + ", ".join(report.conflicts) + "."
    msg += _format_errors([*report.pull.errors, *report.push.errors])
    return CalSyncOutcome(True, "Calendar sync", msg)


def _repo_context(ctx: DotoContext, repo: Any) -> DotoContext:
    """Build a per-repo :class:`DotoContext` targeting one repository.

    Reuses the TUI data helpers so the repo's own ``.doto.toml`` (including its
    ``[calendar]`` table, id prefix, and defaults) and its ``.doto/tasks.json``
    store drive the sync -- exactly as ``gather_tasks`` reads that repo for
    display. The formatter and the shared global state are inherited from the
    launch context.
    """
    from doxtr_doto.cli.main import DotoContext as _DotoContext
    from doxtr_doto.cli.tui.data import config_for_repo, store_for_repo

    repo_config = config_for_repo(repo, ctx.config)
    return _DotoContext(
        config=repo_config,
        store=store_for_repo(repo),
        formatter=ctx.formatter,
        global_store=ctx.global_store,
    )


def displayed_sync_repos(ctx: DotoContext, *, scope: Any, repo_filter: Any) -> list[Any]:
    """Return the displayed repos that have calendar sync enabled.

    The set mirrors what the TUI is *showing*:

    * LOCAL scope -> only the launch-directory repo.
    * GLOBAL scope -> every discovered repo, narrowed by the active
      ``repo_filter`` when one is set (the same filter the task list honours).

    Each candidate's own ``.doto.toml`` is consulted and only repos whose
    ``[calendar]`` is enabled with a provider are returned, so a mixed project
    (some repos synced, some not) only syncs the ones configured for it.

    Args:
        ctx: The launch context (fallback config + global state).
        scope: The active :class:`~doxtr_doto.cli.display.DisplayScope`.
        repo_filter: The active repo-filter names (GLOBAL only); empty/None
            means "all displayed repos".

    Returns:
        A list of discovered-repo objects whose calendar sync is enabled.
    """
    from doxtr_doto.cli.display import DisplayScope
    from doxtr_doto.cli.tui.data import current_repo, list_repos

    if scope is DisplayScope.GLOBAL:
        candidates = list(list_repos(ctx))
        wanted = set(repo_filter or ())
        if wanted:
            candidates = [r for r in candidates if r.name in wanted]
    else:
        candidates = [current_repo(ctx)]

    enabled: list[Any] = []
    for repo in candidates:
        repo_ctx = _repo_context(ctx, repo)
        cal = repo_ctx.config.calendar
        if cal.enabled and cal.provider and not cal.validate():
            enabled.append(repo)
    return enabled


def sync_displayed(
    ctx: DotoContext,
    *,
    scope: Any,
    repo_filter: Any = None,
    exclude_done: bool = False,
) -> CalSyncOutcome:
    """Sync every *displayed* repo that has calendar sync enabled.

    This is the ``C s`` entry point: rather than syncing only the launch
    directory, it syncs each repo the TUI is currently showing (per ``scope``
    and ``repo_filter``) that is itself configured for calendar sync -- the
    behaviour most users expect when they have selected a synced repo to work
    on. Each repo is synced with its *own* config (direction, conflict policy,
    calendar, credentials) via :func:`sync`, and the per-repo outcomes are
    aggregated into one notification.

    When no displayed repo has calendar sync enabled, returns a clear
    not-configured outcome (so pressing ``C s`` in an unsynced view is not a
    silent no-op).

    Args:
        ctx: The launch context.
        scope: The active display scope.
        repo_filter: The active repo-filter names (GLOBAL only).
        exclude_done: Keep completed tasks off the calendar (passed through).

    Returns:
        An aggregated :class:`CalSyncOutcome`.
    """
    repos = displayed_sync_repos(ctx, scope=scope, repo_filter=repo_filter)
    if not repos:
        return CalSyncOutcome(
            False,
            "Calendar sync",
            "No displayed repository has calendar sync enabled. Add a "
            "[calendar] section to the repo's .doto.toml.",
        )

    # Single displayed repo: return its outcome directly (keeps the common
    # case's message identical to a plain per-repo sync).
    if len(repos) == 1:
        return sync(_repo_context(ctx, repos[0]), exclude_done=exclude_done)

    lines: list[str] = []
    any_fail = False
    for repo in repos:
        outcome = sync(_repo_context(ctx, repo), exclude_done=exclude_done)
        any_fail = any_fail or not outcome.ok
        lines.append(f"{repo.name}: {outcome.message}")
    return CalSyncOutcome(not any_fail, "Calendar sync", "\n".join(lines))


def _format_errors(errors: list[tuple[str, str]]) -> str:
    """Append a compact per-item error list to a summary (empty when none)."""
    if not errors:
        return ""
    joined = "; ".join(f"{ident}: {msg}" for ident, msg in errors)
    return f" Errors - {joined}"
