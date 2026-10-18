"""doto update command - Update task fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.commands.add import open_editor, parse_relative_date
from doxtr_doto.cli.completion import (
    complete_assignee,
    complete_date,
    complete_priority,
    complete_status,
    complete_tag,
    complete_task_id,
)
from doxtr_doto.cli.validators import validate_priority, validate_status

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter
    from doxtr_doto.sync.json_store import JsonTaskStore


def _is_task_overdue(task: dict[str, Any]) -> bool:
    """Check if a task is overdue.

    Thin wrapper over :func:`doxtr_doto.date_utils.task_is_overdue`, the single
    source of truth for the "past due and not done" rule, kept so the
    ``--filter-overdue`` call site reads clearly.

    Args:
        task: Task data dictionary.

    Returns:
        True if task has a due date in the past and is not done.
    """
    from doxtr_doto.date_utils import task_is_overdue

    return task_is_overdue(task)


def _build_updates(
    task: Mapping[str, Any],
    title: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    clear_due: bool,
    estimate: str | None = None,
    clear_estimate: bool = False,
    add_tags: str | None = None,
    remove_tags: str | None = None,
    depends_on: str | None = None,
    add_depends: str | None = None,
    remove_depends: str | None = None,
    body: str | None = None,
    edit: bool = False,
    raci: str | None = None,
) -> dict[str, Any]:
    """Build the updates dictionary for a task.

    Args:
        task: Current task data.
        title: New title or None.
        assignee: New assignee or None.
        priority: New priority or None.
        status: New status or None.
        due: New due date or None.
        clear_due: Whether to clear the due date.
        estimate: New time estimate (duration string) or None.
        clear_estimate: Whether to clear the time estimate.
        add_tags: Tags to add (comma-separated) or None.
        remove_tags: Tags to remove (comma-separated) or None.
        depends_on: Dependencies to set (comma-separated) or None.
        add_depends: Dependencies to add (comma-separated) or None.
        remove_depends: Dependencies to remove (comma-separated) or None.
        body: New body or None.
        edit: Whether to open editor for body (only for single task).
        raci: RACI string to merge into existing RACI, or None.

    Returns:
        Dictionary of updates to apply.
    """
    updates: dict[str, Any] = {}

    if title is not None:
        updates["title"] = title

    if assignee is not None:
        updates["assignee"] = assignee if assignee else None

    if priority is not None:
        updates["priority"] = priority

    if status is not None:
        updates["status"] = status

    if clear_due:
        updates["due"] = None
    elif due is not None:
        updates["due"] = parse_relative_date(due)

    if clear_estimate:
        updates["estimate"] = None
    elif estimate is not None:
        from doxtr_doto.date_utils import parse_duration

        # ``estimate`` is a Click string option, so ``parse_duration`` can only
        # raise ``ValueError`` here (``TypeError`` is reserved for non-string,
        # non-numeric inputs, which the CLI never produces).
        try:
            updates["estimate"] = parse_duration(estimate)
        except ValueError as err:
            raise click.BadParameter(str(err), param_hint="--estimate") from err

    # Handle tags
    if add_tags or remove_tags:
        current_tags = set(task.get("tags", []))
        if add_tags:
            for tag in add_tags.split(","):
                tag = tag.strip()
                if tag:
                    current_tags.add(tag)
        if remove_tags:
            for tag in remove_tags.split(","):
                tag = tag.strip()
                current_tags.discard(tag)
        updates["tags"] = sorted(current_tags)

    # Handle dependencies
    if depends_on is not None:
        # Replace all dependencies
        updates["depends_on"] = [d.strip() for d in depends_on.split(",") if d.strip()]
    elif add_depends or remove_depends:
        current_deps = set(task.get("depends_on", []))
        if add_depends:
            for dep in add_depends.split(","):
                dep = dep.strip()
                if dep:
                    current_deps.add(dep)
        if remove_depends:
            for dep in remove_depends.split(","):
                dep = dep.strip()
                current_deps.discard(dep)
        updates["depends_on"] = sorted(current_deps)

    # Handle body
    if edit:
        current_body = task.get("body", "")
        updates["body"] = open_editor(current_body)
    elif body is not None:
        updates["body"] = body

    # Handle RACI (merge with existing)
    if raci is not None:
        from doxtr_doto.raci import merge_raci, parse_raci

        new_raci = parse_raci(raci)
        if new_raci:
            existing_raci = task.get("raci")
            updates["raci"] = merge_raci(existing_raci, new_raci)

    return updates


@click.command("update")
@click.argument("task_id", required=False, shell_complete=complete_task_id)
@click.option("--title", "-T", help="New title.")
@click.option("--assignee", "-a", shell_complete=complete_assignee, help="New assignee.")
@click.option(
    "--priority",
    "-p",
    callback=validate_priority,
    shell_complete=complete_priority,
    help="New priority.",
)
@click.option(
    "--status",
    "-s",
    callback=validate_status,
    shell_complete=complete_status,
    help="New status.",
)
@click.option(
    "--due",
    "-d",
    shell_complete=complete_date,
    help="New due date (YYYY-MM-DD or relative: +7d, friday), optional time: 'friday 16:00'.",
)
@click.option("--clear-due", is_flag=True, help="Clear the due date.")
@click.option(
    "--estimate",
    help="New time estimate (e.g. '5m', '90m', '4h', '1h30m', or a bare number of minutes).",
)
@click.option("--clear-estimate", is_flag=True, help="Clear the time estimate.")
@click.option("--add-tags", shell_complete=complete_tag, help="Tags to add (comma-separated).")
@click.option(
    "--remove-tags", shell_complete=complete_tag, help="Tags to remove (comma-separated)."
)
@click.option(
    "--depends-on",
    "-D",
    shell_complete=complete_task_id,
    help="Set dependency task IDs (comma-separated).",
)
@click.option(
    "--add-depends",
    shell_complete=complete_task_id,
    help="Add dependency task IDs (comma-separated).",
)
@click.option(
    "--remove-depends",
    shell_complete=complete_task_id,
    help="Remove dependency task IDs (comma-separated).",
)
@click.option("--body", "-b", help="New task description/body.")
@click.option("--edit", "-e", is_flag=True, help="Open $EDITOR for body.")
@click.option("--raci", help='Merge RACI roles (e.g. "consulted charlie, informed diana").')
# Filter options for bulk updates
@click.option(
    "--filter-status",
    shell_complete=complete_status,
    help="Filter tasks by status (comma-separated).",
)
@click.option(
    "--filter-priority",
    shell_complete=complete_priority,
    help="Filter tasks by priority (comma-separated).",
)
@click.option(
    "--filter-assignee",
    shell_complete=complete_assignee,
    help="Filter tasks by assignee (comma-separated).",
)
@click.option(
    "--filter-tags",
    shell_complete=complete_tag,
    help="Filter tasks that have any of these tags (comma-separated).",
)
@click.option(
    "--filter-overdue",
    is_flag=True,
    help="Filter only overdue tasks.",
)
# Bulk operation safety flags
@click.option(
    "--all",
    "all_tasks",
    is_flag=True,
    help="Apply to all non-archived tasks (required when no TASK_ID and using filters).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview which tasks would be updated without making changes.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt for bulk updates.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def update(
    ctx: DotoContext,
    task_id: str | None,
    title: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    clear_due: bool,
    estimate: str | None,
    clear_estimate: bool,
    add_tags: str | None,
    remove_tags: str | None,
    depends_on: str | None,
    add_depends: str | None,
    remove_depends: str | None,
    body: str | None,
    edit: bool,
    raci: str | None,
    filter_status: str | None,
    filter_priority: str | None,
    filter_assignee: str | None,
    filter_tags: str | None,
    filter_overdue: bool,
    all_tasks: bool,
    dry_run: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Update fields of an existing task or bulk update multiple tasks.

    TASK_ID is the identifier of a single task to update. When omitted,
    use filter options to select multiple tasks for bulk update.

    Examples:

        # Single task update
        doto update DOTO-001 --status done

        # Bulk update: set all high-priority tasks to in-progress
        doto update --filter-priority high --status in-progress --all

        # Bulk update: add tag to all overdue tasks
        doto update --filter-overdue --add-tags needs-attention --all

        # Preview bulk update without making changes
        doto update --filter-status open --priority high --all --dry-run

        # Skip confirmation for bulk update
        doto update --filter-assignee alice --status done --all --yes
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    # Determine if this is a single-task or bulk update
    has_filters = any(
        [
            filter_status,
            filter_priority,
            filter_assignee,
            filter_tags,
            filter_overdue,
        ]
    )

    # Single task update mode
    if task_id:
        if has_filters or all_tasks:
            raise click.UsageError("Cannot use filter options or --all when TASK_ID is provided.")
        _update_single_task(
            ctx=ctx,
            store=store,
            formatter=formatter,
            task_id=task_id,
            title=title,
            assignee=assignee,
            priority=priority,
            status=status,
            due=due,
            clear_due=clear_due,
            estimate=estimate,
            clear_estimate=clear_estimate,
            add_tags=add_tags,
            remove_tags=remove_tags,
            depends_on=depends_on,
            add_depends=add_depends,
            remove_depends=remove_depends,
            body=body,
            edit=edit,
            json_output=json_output,
            raci=raci,
        )
        return

    # Bulk update mode
    if not has_filters and not all_tasks:
        raise click.UsageError("Either TASK_ID or filter options (with --all) must be provided.")

    if not all_tasks:
        raise click.UsageError(
            "The --all flag is required when using filters without TASK_ID "
            "to confirm bulk update intent."
        )

    if edit:
        raise click.UsageError("The --edit flag cannot be used with bulk updates.")

    # Parse filter values
    status_list = [s.strip() for s in filter_status.split(",")] if filter_status else None
    priority_list = [p.strip() for p in filter_priority.split(",")] if filter_priority else None
    assignee_list = [a.strip() for a in filter_assignee.split(",")] if filter_assignee else None
    tag_list = [t.strip() for t in filter_tags.split(",")] if filter_tags else None

    # Validate filter values against config
    if status_list:
        valid_statuses = ctx.config.statuses
        for s in status_list:
            if s not in valid_statuses:
                raise click.ClickException(
                    f"Invalid status '{s}'. Valid options: {', '.join(valid_statuses)}"
                )

    if priority_list:
        valid_priorities = ctx.config.priorities
        for p in priority_list:
            if p not in valid_priorities:
                raise click.ClickException(
                    f"Invalid priority '{p}'. Valid options: {', '.join(valid_priorities)}"
                )

    # Get matching tasks using the store's filter method
    tasks = store.filter_tasks(
        assignee=assignee_list,
        priority=priority_list,
        status=status_list,
        tags=tag_list,
        include_archived=False,
    )

    # Apply overdue filter if requested
    if filter_overdue:
        tasks = [t for t in tasks if _is_task_overdue(t)]

    if not tasks:
        if json_output:
            formatter.print_json({"updated": [], "message": "No tasks match the filter criteria."})
        else:
            formatter.print_warning("No tasks match the filter criteria.")
        return

    # Check that we have updates to apply
    # Build a sample updates dict to verify something will change
    sample_task = tasks[0]
    sample_updates = _build_updates(
        task=sample_task,
        title=title,
        assignee=assignee,
        priority=priority,
        status=status,
        due=due,
        clear_due=clear_due,
        estimate=estimate,
        clear_estimate=clear_estimate,
        add_tags=add_tags,
        remove_tags=remove_tags,
        depends_on=depends_on,
        add_depends=add_depends,
        remove_depends=remove_depends,
        body=body,
        edit=False,
        raci=raci,
    )

    if not sample_updates:
        raise click.UsageError("No updates specified.")

    # Dry run mode
    if dry_run:
        _handle_dry_run(
            formatter=formatter,
            tasks=tasks,
            sample_updates=sample_updates,
            json_output=json_output,
        )
        return

    # Confirmation prompt for bulk updates (more than 5 tasks)
    if len(tasks) > 5 and not yes:
        task_ids = [t["id"] for t in tasks]
        formatter.print(f"\nAbout to update {len(tasks)} tasks:")
        for tid in task_ids[:10]:
            formatter.print(f"  - {tid}")
        if len(task_ids) > 10:
            formatter.print(f"  ... and {len(task_ids) - 10} more")
        formatter.print(
            f"\nUpdates to apply: {', '.join(f'{k}={v}' for k, v in sample_updates.items())}"
        )
        if not click.confirm("\nProceed with bulk update?"):
            formatter.print("Aborted.")
            return

    # Apply updates to all matching tasks
    updated_ids = []
    for task in tasks:
        tid = task["id"]
        # Build task-specific updates (tags/deps need per-task handling)
        task_data = store.get_task(tid)
        if task_data is None:
            continue
        updates = _build_updates(
            task=task_data,
            title=title,
            assignee=assignee,
            priority=priority,
            status=status,
            due=due,
            clear_due=clear_due,
            estimate=estimate,
            clear_estimate=clear_estimate,
            add_tags=add_tags,
            remove_tags=remove_tags,
            depends_on=depends_on,
            add_depends=add_depends,
            remove_depends=remove_depends,
            body=body,
            edit=False,
            raci=raci,
        )
        if updates:
            if "depends_on" in updates:
                from doxtr_doto.cli.id_resolver import cross_repo_deps

                offending = cross_repo_deps(ctx, store, list(updates["depends_on"]))
                if offending:
                    raise click.ClickException(
                        "Cross-repo dependencies are not supported: "
                        f"{', '.join(offending)}. A dependency must live in the "
                        "same repository as the task."
                    )
            store.update_task(tid, updates)
            updated_ids.append(tid)

    # Save changes
    if updated_ids:
        store.save()
        from doxtr_doto.cli import known_names
        from doxtr_doto.raci import raci_names

        known_names.remember_task_names(
            sample_updates.get("assignee"), sample_updates.get("tags", [])
        )
        for rn in raci_names(sample_updates.get("raci")):
            known_names.remember_task_names(rn, [])

    # Output results
    if json_output:
        formatter.print_json(
            {
                "updated": updated_ids,
                "count": len(updated_ids),
            }
        )
    else:
        formatter.print_success(f"Updated {len(updated_ids)} task(s).")
        for tid in updated_ids:
            formatter.print(f"  - {tid}")


def _update_single_task(
    ctx: DotoContext,
    store: JsonTaskStore,
    formatter: OutputFormatter,
    task_id: str,
    title: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    clear_due: bool,
    estimate: str | None,
    clear_estimate: bool,
    add_tags: str | None,
    remove_tags: str | None,
    depends_on: str | None,
    add_depends: str | None,
    remove_depends: str | None,
    body: str | None,
    edit: bool,
    json_output: bool,
    raci: str | None = None,
) -> None:
    """Update a single task by ID (original behavior)."""
    from doxtr_doto.cli.id_resolver import resolve_task_ref

    resolved = resolve_task_ref(ctx, task_id)
    if resolved is None:
        raise click.ClickException(f"Task '{task_id}' not found.")
    store = resolved.store
    local_id = resolved.task_id

    # Get task
    task = store.get_task(local_id)
    if task is None:
        raise click.ClickException(f"Task '{task_id}' not found.")

    # Build updates
    updates = _build_updates(
        task=task,
        title=title,
        assignee=assignee,
        priority=priority,
        status=status,
        due=due,
        clear_due=clear_due,
        estimate=estimate,
        clear_estimate=clear_estimate,
        add_tags=add_tags,
        remove_tags=remove_tags,
        depends_on=depends_on,
        add_depends=add_depends,
        remove_depends=remove_depends,
        body=body,
        edit=edit,
        raci=raci,
    )

    # Check if any updates
    if not updates:
        raise click.UsageError("No updates specified.")

    # Reject cross-repo dependencies (see cross_repo_deps): a dependency must
    # live in the same repository as the task, mirroring the parent link.
    if "depends_on" in updates:
        from doxtr_doto.cli.id_resolver import cross_repo_deps

        offending = cross_repo_deps(ctx, store, list(updates["depends_on"]))
        if offending:
            raise click.ClickException(
                "Cross-repo dependencies are not supported: "
                f"{', '.join(offending)}. A dependency must live in the same "
                "repository as the task."
            )

    # Apply updates
    store.update_task(local_id, updates)
    store.save()
    from doxtr_doto.cli import known_names
    from doxtr_doto.raci import raci_names

    known_names.remember_task_names(updates.get("assignee"), updates.get("tags", []))
    for rn in raci_names(updates.get("raci")):
        known_names.remember_task_names(rn, [])

    # Display result
    formatter.print_success(f"Updated task {task_id}")
    if not formatter.quiet:
        updated_task = store.get_task(local_id)
        if updated_task is not None:
            formatter.format_task_detail({"id": task_id, **updated_task})


def _handle_dry_run(
    formatter: OutputFormatter,
    tasks: list[dict[str, Any]],
    sample_updates: dict[str, Any],
    json_output: bool,
) -> None:
    """Handle dry-run mode output."""
    task_ids = [t["id"] for t in tasks]

    if json_output:
        formatter.print_json(
            {
                "dry_run": True,
                "would_update": task_ids,
                "count": len(task_ids),
                "updates": sample_updates,
            }
        )
    else:
        formatter.print(f"\nDry run: Would update {len(tasks)} task(s):")
        for task in tasks:
            tid = task["id"]
            task_title = task.get("title", "")[:50]
            task_status = task.get("status", "")
            formatter.print(f"  - {tid}: [{task_status}] {task_title}")
        formatter.print("\nUpdates that would be applied:")
        for key, value in sample_updates.items():
            formatter.print(f"  {key}: {value}")
