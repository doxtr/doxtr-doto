"""Modular, overridable widgets for the doto 3-pane TUI.

Each pane is a small widget class so a child theme can subclass or replace it
without rewriting the app. Row formatting is delegated to classmethods
(``format_*``) that return Textual markup strings, keeping presentation logic
isolated from mutation and layout.

Scrolling the alt-views (list / kanban / calendar) distinguishes two kinds of
cursor move. Continuous ``j``/``k`` navigation uses the *smart-scroll*
algorithm (:meth:`AltLayoutView.scroll_to_cursor` /
:meth:`AltLayoutView.target_scroll_y`), which only scrolls when the cursor
comes within a margin of an edge and infers the move direction from the
previous cursor line. *Discontinuous* jumps - switching kanban swim lanes,
selecting a task by id in the list / kanban views, or a layout cycle that
re-selects a task - cannot rely on direction inference (the cursor can land
arbitrarily far from where it was), so they go through
:meth:`AltLayoutView.ensure_cursor_visible`, which repositions the viewport so
the *whole* selected item is on screen regardless of the previous position.
Both paths are overridable seams; :class:`CalendarView` overrides them to keep
its month grid pinned to the top (its day move / select-by-id reach their
scroll through the subsequent rebuild rather than this seam, which is reached
only when a layout cycle lands on the calendar), so a child theme can retune
the scroll feel for either kind of move.

This module imports ``textual`` directly; it is only imported from
:mod:`doxtr_doto.cli.tui.app`, which is in turn only loaded when the optional
``textual`` dependency is installed.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Callable, Sequence
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from typing import TYPE_CHECKING, Any, cast

from rich.console import Console as _Console
from rich.text import Text as _Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static, Tree

from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.global_state import DEFAULT_WORKWEEK_DAYS
from doxtr_doto.cli.session import format_duration
from doxtr_doto.cli.tui.filtersort import TreeRow, flatten_tree, pin_active_first
from doxtr_doto.cli.tui.theme import (
    escape_markup,
    escape_title,
    priority_style,
    status_style,
    styled,
)
from doxtr_doto.constants import DONE_STATUS, WEEKDAY_ABBR
from doxtr_doto.sync.json_store import WorkLog
from doxtr_doto.work_report import month_range, week_range, year_range

if TYPE_CHECKING:
    from doxtr_doto.cli.tui.app import DotoApp

#: A width-agnostic Rich console reused only to measure how many display lines
#: a row's markup wraps to (:meth:`ListView.row_height`). The width is passed
#: to each ``Text.wrap`` call, so the console itself holds no per-view state;
#: a module-level singleton avoids rebuilding one on every keypress.
_MEASURE_CONSOLE = _Console()


class TitleHighlight:
    """Mixin giving a widget an overridable title-escape + accent seam.

    Free-text titles are escaped (so bracketed text such as ``"[WIP] fix"``
    renders literally and keeps its true width) and each ``[...]`` run is drawn
    in :attr:`BRACKET_HIGHLIGHT_STYLE`. The style is a *class attribute* - the
    same override idiom as :attr:`KanbanView.FRAME_STYLE` /
    :attr:`KanbanView.ACTIVE_COLUMN_STYLE` - so a child theme restyles the
    highlight by subclassing and resetting the attribute (per widget, if it
    wants different hues per surface), and the live app publishes the active
    theme accent once by writing ``TitleHighlight.BRACKET_HIGHLIGHT_STYLE``
    (which every subclass inherits unless it overrides). The empty default
    keeps pure-logic callers/tests colour-free and width-stable.

    :meth:`escape_title` is the single overridable method every title surface
    routes through, so a child theme can also replace the escape/highlight
    behaviour wholesale without touching each ``format_*``.
    """

    #: Markup style applied to ``[...]`` runs inside titles so a tag such as
    #: ``"[WIP]"`` is drawn in the active theme's accent colour (the hue the
    #: Textual footer uses for key labels like ``tab``). The live TUI sets this
    #: at mount / theme-change with the resolved accent hex
    #: (:meth:`DotoApp.refresh_accent_highlights`); it must be a markup value
    #: both rich and Textual understand (a concrete colour like ``"#ffa62b"`` -
    #: *not* a ``$accent`` CSS token, which rich markup cannot resolve).
    #: Overridable per widget class.
    BRACKET_HIGHLIGHT_STYLE: str = ""

    @classmethod
    def escape_title(cls, value: object) -> str:
        """Escape ``value`` and accent-highlight its ``[...]`` runs.

        Delegates to :func:`doxtr_doto.cli.tui.theme.escape_title` with this
        class's :attr:`BRACKET_HIGHLIGHT_STYLE`. A child theme overrides this
        (or just the attribute) to change how titles are escaped/highlighted.

        Args:
            value: The free-text title to escape and highlight.

        Returns:
            The escaped, accent-highlighted Textual markup string.
        """
        return escape_title(value, cls.BRACKET_HIGHLIGHT_STYLE)


class RepoTree(Tree[None]):
    """Left pane: repository tree, favorites, and scope indicator.

    The tree is rebuilt from the cached registry. The root label reflects the
    active :class:`DisplayScope` so the user always sees whether they are in a
    single-repo (local) or aggregated (global) view. Selecting a repository
    leaf toggles it in the repo filter
    (:attr:`doxtr_doto.cli.tui.filtersort.ViewPrefs.repo_filter`), handled by
    the app's tree-node-selected handler; each selected repo leaf is marked by
    :meth:`format_marker` (overridable), mirroring
    :meth:`TaskList.format_marker`.
    """

    def rebuild(
        self,
        repos: list[Any],
        favorites: list[str],
        scope: DisplayScope,
        current_repo: str,
        selected_repos: set[str] | None = None,
    ) -> None:
        """Rebuild the tree from registry data.

        Args:
            repos: Discovered repositories from the cache.
            favorites: Favorited repo names.
            scope: The active display scope.
            current_repo: The current working directory's repo name.
            selected_repos: The repository names currently in the repo filter
                (:attr:`doxtr_doto.cli.tui.filtersort.ViewPrefs.repo_filter`),
                so each selected repo leaf is marked. None/empty means no repo
                is selected (the GLOBAL "show all" state).
        """
        selected = selected_repos or set()
        self.clear()
        self.root.label = self.format_root(scope)
        self.root.expand()

        fav_node = self.root.add("★ Favorites", expand=True)
        if favorites:
            for name in favorites:
                fav_node.add_leaf(name)
        else:
            fav_node.add_leaf("[dim](none)[/dim]")

        repos_node = self.root.add("Repositories", expand=True)
        if repos:
            for repo in repos:
                # Store the bare repo name on the leaf so the app can recover
                # it on selection to toggle the repo filter.
                repos_node.add_leaf(
                    self.format_repo(repo.name, current_repo, repo.name in selected),
                    data=repo.name,
                )
        else:
            repos_node.add_leaf("[dim](run R to scan)[/dim]")

    @classmethod
    def format_root(cls, scope: DisplayScope) -> str:
        """Return the root label showing the active scope.

        Args:
            scope: The active display scope.

        Returns:
            Textual markup for the root label.
        """
        label = "Global" if scope is DisplayScope.GLOBAL else "Local"
        return f"[bold]Scope: {label}[/bold]"

    @classmethod
    def format_repo(cls, name: str, current_repo: str, selected: bool = False) -> str:
        """Return a repo tree-leaf label, highlighting the current repo.

        A leading selection marker (:meth:`format_marker`) indicates whether
        the repo is currently part of the repo filter
        (:attr:`doxtr_doto.cli.tui.filtersort.ViewPrefs.repo_filter`).

        Args:
            name: The repository name.
            current_repo: The current working directory's repo name.
            selected: Whether the repo is in the repo filter.

        Returns:
            Textual markup for the leaf label.
        """
        marker = cls.format_marker(selected)
        safe_name = escape_markup(name)
        if name == current_repo:
            return f"{marker}[bold reverse]{safe_name}[/bold reverse] (here)"
        return f"{marker}{safe_name}"

    @classmethod
    def format_marker(cls, selected: bool) -> str:
        """Return the leading selection marker for a repo leaf.

        Overridable so a child theme can change the selection glyph without
        touching :meth:`format_repo`, mirroring
        :meth:`TaskList.format_marker`.

        Args:
            selected: Whether the repo is in the repo filter.

        Returns:
            Textual markup for the leading marker (a trailing space keeps the
            label aligned whether or not the repo is selected).
        """
        return "[reverse]\u2714[/reverse] " if selected else "  "


class TreePrefixMixin:
    """Shared tree triangle + depth-indent prefix for the list widgets.

    Holds the overridable tree glyph/indent class attributes and the
    :meth:`format_tree_prefix` seam that :class:`TaskList` (table layout) and
    :class:`ListView` (list layout) both draw their expand/collapse affordance
    from, so the prefix logic lives in one place. Both widgets inherit this
    mixin, and each can still override any ``TREE_*`` attribute or
    :meth:`format_tree_prefix` *independently* via normal subclass attribute
    resolution (a child theme reskins the table and list trees separately).
    """

    #: Number of leading spaces per nesting depth level drawn by
    #: :meth:`format_tree_prefix`. A child theme can widen/narrow the tree
    #: indent by subclassing and resetting this attribute.
    TREE_INDENT: int = 2
    #: The expand/collapse/leaf glyphs drawn by :meth:`format_tree_prefix`,
    #: matching the repo explorer's Textual ``Tree`` look (expanded, collapsed,
    #: leaf). Overridable per widget class so a child theme can reskin the tree
    #: markers without reimplementing :meth:`format_tree_prefix`.
    TREE_GLYPH_EXPANDED: str = "\u25be"  # ▾
    TREE_GLYPH_COLLAPSED: str = "\u25b6"  # ▶
    TREE_GLYPH_LEAF: str = " "

    @classmethod
    def format_tree_prefix(cls, depth: int, has_children: bool, expanded: bool) -> str:
        """Return the tree triangle + depth indent prefix for a row title.

        The single overridable seam for the parent/child tree affordance
        (mirroring :meth:`TaskList.format_marker` / :meth:`TaskList.format_tags`):
        it produces the leading glyph + indentation prepended to a row's title
        so the list reads as an expandable tree. A child theme restyles the
        tree by subclassing and resetting :attr:`TREE_INDENT` /
        :attr:`TREE_GLYPH_EXPANDED` / :attr:`TREE_GLYPH_COLLAPSED` /
        :attr:`TREE_GLYPH_LEAF`, or overriding this method wholesale - on
        :class:`TaskList` or :class:`ListView` independently.

        The prefix is width-stable: every row is indented ``depth`` levels and
        then carries exactly one glyph cell (a triangle for a parent, a blank
        for a leaf) followed by a space, so sibling titles line up regardless
        of whether a given row has children.

        Args:
            depth: The row's nesting level (0 for a root).
            has_children: Whether the row has visible children (draws a
                triangle rather than the leaf blank).
            expanded: Whether the row's children are shown (``▾`` vs ``▶``);
                only meaningful when ``has_children`` is True.

        Returns:
            The Textual-markup-safe prefix string for the row title.
        """
        indent = " " * (cls.TREE_INDENT * max(depth, 0))
        if has_children:
            glyph = cls.TREE_GLYPH_EXPANDED if expanded else cls.TREE_GLYPH_COLLAPSED
        else:
            glyph = cls.TREE_GLYPH_LEAF
        return f"{indent}{glyph} "


class TaskList(TreePrefixMixin, TitleHighlight, DataTable[str]):
    """Middle pane: the task list.

    Each row carries a running indicator, a done checkbox, priority/tag
    badges and the title. The bare/namespaced id for the selected row is kept
    in :attr:`row_ids` so the app can resolve the current cursor selection.

    Separately from the cursor, the list tracks a *multi-selection* set
    (:attr:`selected_ids`): ids toggled on with Space. When the set is
    non-empty, bulk actions (done / cycle status) operate on every selected
    task via :meth:`target_ids`; when it is empty they fall back to the single
    cursor task. Selected rows are visually marked by :meth:`format_marker`,
    which a child theme can override.

    Sub-tasks are nested under their ``parent`` (see
    :class:`doxtr_doto.sync.json_store.TaskData`) as an expandable tree:
    :meth:`rebuild` flattens the visible list through
    :func:`doxtr_doto.cli.tui.filtersort.flatten_tree`, and each row is drawn
    with a leading expand/collapse triangle + depth indentation produced by
    the overridable :meth:`format_tree_prefix` seam. The set of *collapsed*
    parent ids is owned by the app (session-scoped) and passed into each
    :meth:`rebuild`; parents default to expanded. Which rows have children is
    cached in :attr:`row_has_children` so the app can decide whether Space
    toggles expansion (parent row) or multi-selection (leaf row).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the task list, its id tracking, and its selection set."""
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.row_ids: list[str] = []
        #: Ids toggled into the multi-selection via Space.
        self.selected_ids: set[str] = set()
        #: Per-row "has visible children" flag, one entry per :attr:`row_ids`
        #: entry in the same order. Populated by :meth:`rebuild` so the app
        #: can tell whether Space should toggle the row's tree expansion
        #: (parent) or its multi-selection (leaf).
        self.row_has_children: list[bool] = []

    def rebuild(self, tasks: list[dict[str, Any]], collapsed_ids: set[str] | None = None) -> None:
        """Rebuild the table rows from task dicts, nesting sub-tasks as a tree.

        The visible list is flattened into a depth-first pre-order tree via
        :func:`doxtr_doto.cli.tui.filtersort.flatten_tree` so each sub-task is
        drawn indented under its ``parent`` with an expand/collapse triangle.
        ``collapsed_ids`` is the app-owned (session-scoped) set of parent ids
        whose children are hidden; parents not in it default to expanded.

        The current cursor selection is preserved by id across rebuilds when
        the previously selected task is still present. Any ids in the
        multi-selection that are no longer present are dropped. The active
        (time-recorded) task is already pinned to the top of ``tasks`` by the
        caller's view pipeline (:func:`pin_active_first`, Feature A); this
        method consumes that ordering as-is and does not re-pin, so a child
        theme that overrides the pin step to a no-op is honoured. A running
        sub-task under a collapsed ancestor stays visible because
        :func:`~doxtr_doto.cli.tui.filtersort.flatten_tree` force-expands the
        ancestor chain of any ``_running`` task.

        Args:
            tasks: Task dicts (as produced by
                :func:`doxtr_doto.cli.tui.data.gather_tasks`).
            collapsed_ids: The set of parent ids whose children are hidden
                (default-expanded otherwise). None is treated as empty (all
                parents expanded).
        """
        previous = self.selected_id()
        self.clear(columns=True)
        self.add_columns("", "", "", "Pri", "Status", "ID", "Title", "Tags")
        self.row_ids = []
        self.row_has_children = []
        # ``tasks`` is already active-pinned by the caller's view pipeline
        # (pin_active_first, Feature A); consume that order as-is rather than
        # re-pinning here, so a child theme that overrides the pin step is
        # honoured. Flatten into the parent/child tree so sub-tasks nest under
        # their parent (a running sub-task under a collapsed ancestor stays
        # visible via flatten_tree's force-expand).
        rows = flatten_tree(tasks, collapsed_ids)
        for row in rows:
            task_id = row.task.get("id", "")
            self.add_row(*self.format_row(row, task_id in self.selected_ids))
            self.row_ids.append(task_id)
            self.row_has_children.append(row.has_children)
        # Drop selections for tasks that no longer exist.
        self.selected_ids &= set(self.row_ids)
        if previous is not None and previous in self.row_ids:
            self.move_cursor(row=self.row_ids.index(previous))

    @classmethod
    def format_row(cls, row: TreeRow | dict[str, Any], selected: bool = False) -> tuple[str, ...]:
        """Return the display cells for a task row.

        Accepts either a :class:`~doxtr_doto.cli.tui.filtersort.TreeRow` (the
        tree-aware path :meth:`rebuild` uses, carrying depth / expansion) or a
        bare task dict (treated as a depth-0 leaf, for pure-logic callers and
        tests that do not build the tree). The Title cell is prefixed with the
        expand/collapse triangle + depth indentation from the overridable
        :meth:`format_tree_prefix` seam.

        Args:
            row: A :class:`TreeRow` or a bare task dict.
            selected: Whether the task is in the multi-selection set.

        Returns:
            A tuple of Textual markup strings, one per column.
        """
        if isinstance(row, TreeRow):
            task = row.task
            depth, has_children, expanded = row.depth, row.has_children, row.expanded
        else:
            task = row
            depth, has_children, expanded = 0, False, False
        marker = cls.format_marker(selected)
        running = "[green]▶[/green]" if task.get("_running") else " "
        done = task.get("status") == DONE_STATUS
        checkbox = "[dim]\\[✓][/dim]" if done else "[ ]"
        priority = task.get("priority") or ""
        pri_cell = styled(priority[:4] or "-", priority_style(priority))
        status = task.get("status") or ""
        status_cell = styled(status or "-", status_style(status))
        task_id = escape_markup(task.get("id", ""))
        prefix = cls.format_tree_prefix(depth, has_children, expanded)
        title = prefix + cls.escape_title(task.get("title", ""))
        tags = task.get("tags") or []
        tag_cell = cls.format_tags(tags)
        return (
            marker,
            running,
            checkbox,
            pri_cell,
            status_cell,
            task_id,
            title,
            tag_cell,
        )

    @classmethod
    def format_marker(cls, selected: bool) -> str:
        """Return the leading multi-select marker cell for a row.

        Overridable so a child theme can change how selected rows are marked
        without touching :meth:`format_row`.

        Args:
            selected: Whether the row's task is in the multi-selection.

        Returns:
            Textual markup for the marker column.
        """
        return "[reverse]\u2714[/reverse]" if selected else " "

    @classmethod
    def format_tags(cls, tags: list[str]) -> str:
        """Return a compact badge string for a task's tags.

        Args:
            tags: The task's tags.

        Returns:
            Textual markup joining the tags as badges.
        """
        if not tags:
            return ""
        return " ".join(f"[blue]#{escape_markup(tag)}[/blue]" for tag in tags)

    def selected_id(self) -> str | None:
        """Return the display id of the currently selected row.

        Returns:
            The selected row's id, or None if the table is empty.
        """
        if not self.row_ids:
            return None
        row = self.cursor_row
        if row is None or row < 0 or row >= len(self.row_ids):
            return None
        return self.row_ids[row]

    def select_id(self, task_id: str) -> bool:
        """Move the row cursor to the row whose id equals ``task_id``.

        Uses the :class:`~textual.widgets.DataTable` row cursor move
        (:meth:`~textual.widgets.DataTable.move_cursor`) so the table's built-in
        scroll-into-view runs, keeping the selected row visible exactly as
        ``j``/``k`` navigation does. See :meth:`AltLayoutView.select_id` for the
        overall contract.

        Args:
            task_id: The display id (bare or namespaced) to select.

        Returns:
            True when ``task_id`` is a current row and the cursor moved to it,
            False when it is not present.
        """
        if task_id not in self.row_ids:
            return False
        self.move_cursor(row=self.row_ids.index(task_id))
        return True

    def cursor_has_children(self) -> bool:
        """Return whether the current cursor row is an expandable parent.

        Reads the per-row :attr:`row_has_children` flag (populated by
        :meth:`rebuild` from the flattened tree) for the current cursor row,
        so the app can decide whether Space toggles the row's tree expansion
        (a parent) or its multi-selection (a leaf). False when there is no
        selectable row.

        Returns:
            True when the cursor row has visible children, else False.
        """
        row = self.cursor_row
        if row is None or row < 0 or row >= len(self.row_has_children):
            return False
        return self.row_has_children[row]

    def toggle_selected(self, task_id: str | None = None) -> None:
        """Toggle a task's membership in the multi-selection set.

        Args:
            task_id: The id to toggle. Defaults to the current cursor row's
                id; a no-op when there is no selectable row.
        """
        target = task_id if task_id is not None else self.selected_id()
        if target is None:
            return
        if target in self.selected_ids:
            self.selected_ids.discard(target)
        else:
            self.selected_ids.add(target)

    def clear_selection(self) -> None:
        """Clear the multi-selection set."""
        self.selected_ids.clear()

    def target_ids(self) -> list[str]:
        """Return the effective target id list for a bulk action.

        Returns the multi-selection set (in row order) when it is non-empty,
        otherwise the single cursor row's id. Empty when nothing is
        selectable.

        Returns:
            The list of task ids a done/cycle action should operate on.
        """
        if self.selected_ids:
            return [rid for rid in self.row_ids if rid in self.selected_ids]
        current = self.selected_id()
        return [current] if current is not None else []


class TaskDetails(TitleHighlight, Static):
    """Lower (bottom) pane: task details and the session interval log.

    In the table layout this pane is stacked *below* the task list (inside the
    ``#task-pane`` column, to the right of the repo tree); its share of the
    height is set by the ``c`` -> ``d`` detail-size ratio.
    """

    #: Allow the details pane to receive focus so Tab can cycle to it.
    can_focus = True

    #: Rebind ``tab``/``shift+tab`` to the app's pane-cycle actions. Without
    #: this, Textual's default screen-level focus traversal consumes ``tab``
    #: (and ``shift+tab``) while the details pane is focused and moves focus to
    #: the next/previous focusable widget *before* the app's ``cycle_pane`` /
    #: ``cycle_pane_reverse`` binding can fire - so the app could never drive
    #: the step *out* of the details pane (e.g. the kanban layout's Tab cycle
    #: wrapping from details back to the first swim lane, or Shift+Tab's
    #: reverse wrap to the last lane). Routing both keys through the app keeps
    #: the whole cycle under app control in every layout, mirroring
    #: :class:`AltLayoutView`'s own ``tab``/``shift+tab`` rebinds.
    BINDINGS = [
        ("tab", "details_cycle_pane", "Cycle pane"),
        # Bind both ``shift+tab`` and ``back_tab`` - some terminals deliver the
        # physical Shift+Tab as ``back_tab`` - so reverse cycling works from
        # the details pane regardless of the key name (see DotoApp.BINDINGS).
        ("shift+tab", "details_cycle_pane_reverse", "Cycle pane (reverse)"),
        ("back_tab", "details_cycle_pane_reverse", "Cycle pane (reverse)"),
    ]

    def action_details_cycle_pane(self) -> None:
        """Delegate Tab from the details pane to the app's forward cycle."""
        cast("DotoApp", self.app).action_cycle_pane()

    def action_details_cycle_pane_reverse(self) -> None:
        """Delegate Shift+Tab from the details pane to the app's reverse cycle."""
        cast("DotoApp", self.app).action_cycle_pane_reverse()

    def update_task(
        self,
        task: dict[str, Any] | None,
        intervals: list[tuple[str, str, str, bool]],
    ) -> None:
        """Render the details and interval log for a task.

        Args:
            task: The selected task dict, or None.
            intervals: Session interval rows from
                :func:`doxtr_doto.cli.tui.data.session_intervals`.
        """
        self.update(self.format_details(task, intervals))

    @classmethod
    def format_details(
        cls,
        task: dict[str, Any] | None,
        intervals: list[tuple[str, str, str, bool]],
    ) -> str:
        """Return the markup for the details pane.

        Args:
            task: The selected task dict, or None.
            intervals: Session interval rows.

        Returns:
            Textual markup for the details pane.
        """
        if not task:
            return "[dim]No task selected.[/dim]"

        lines: list[str] = []
        task_id = escape_markup(task.get("id", ""))
        title = cls.escape_title(task.get("title", ""))
        lines.append(f"[bold]{task_id}[/bold]  {title}")
        priority = task.get("priority") or "-"
        status = task.get("status") or "-"
        lines.append(
            f"Priority: {styled(priority, priority_style(priority))}   "
            f"Status: {styled(status, status_style(status))}"
        )
        if task.get("assignee"):
            lines.append(f"Assignee: {escape_markup(task['assignee'])}")
        if task.get("due"):
            lines.append(f"Due: {escape_markup(task['due'])}")
        if task.get("parent"):
            lines.append(f"Parent: {escape_markup(task['parent'])}")
        tags = task.get("tags") or []
        if tags:
            lines.append("Tags: " + cls.format_tags(tags))
        if task.get("body"):
            lines.append("")
            # Markup-escape the body (matching the shared CLI card builder's
            # plain-escaped body) so a value containing ``[`` / ``]`` - e.g. a
            # Markdown link ``[text](url)`` - renders literally instead of its
            # ``[text]`` run being parsed as a style tag and silently dropped.
            lines.append(cls.format_body(task["body"]))

        lines.append("")
        lines.append("[bold]Sessions[/bold]")
        if not intervals:
            lines.append("[dim](no sessions)[/dim]")
        else:
            for start, stop, duration, is_open in intervals:
                lines.append(cls.format_interval(start, stop, duration, is_open))
        return "\n".join(lines)

    @classmethod
    def format_body(cls, body: object) -> str:
        """Escape a task body for the details pane (overridable seam).

        Routed through a classmethod so a child theme can replace body
        rendering (e.g. real hyperlinks, custom highlighting) without
        overriding the whole :meth:`format_details`.
        """
        return escape_markup(str(body))

    @classmethod
    def format_tags(cls, tags: list[str]) -> str:
        """Return a compact badge string for a task's tags.

        Delegates to :meth:`TaskList.format_tags` by default; defined here so
        a child app replacing the details pane via ``task_details_class`` can
        override tag rendering without being forced through ``TaskList``.

        Args:
            tags: The task's tags.

        Returns:
            Textual markup joining the tags as badges.
        """
        return TaskList.format_tags(tags)

    @classmethod
    def format_interval(cls, start: str, stop: str, duration: str, is_open: bool) -> str:
        """Return one interval-log line.

        Args:
            start: Start timestamp.
            stop: Stop timestamp (or a running marker).
            duration: Human-readable duration.
            is_open: Whether this is the live/open interval.

        Returns:
            Textual markup for the interval row.
        """
        marker = "[green]▶[/green] " if is_open else "  "
        line = f"{marker}{start} -> {stop} ({duration})"
        if is_open:
            return f"[cyan]{line}[/cyan]"
        return line


class StatusLine(Static):
    """Persistent status line with the two always-visible live counters."""

    def update_counters(
        self,
        work_today: int,
        work_running: bool,
        focus_seconds: int,
    ) -> None:
        """Update the status line with the current counters.

        Args:
            work_today: Elapsed work-clock seconds for today (Layer 1).
            work_running: Whether the work clock is currently running.
            focus_seconds: Elapsed seconds of the open focus session (Layer 2).
        """
        self.update(self.format_counters(work_today, work_running, focus_seconds))

    @classmethod
    def format_counters(
        cls,
        work_today: int,
        work_running: bool,
        focus_seconds: int,
    ) -> str:
        """Return the status-line markup for the live counters.

        Args:
            work_today: Elapsed work-clock seconds for today (Layer 1).
            work_running: Whether the work clock is currently running.
            focus_seconds: Elapsed seconds of the open focus session (Layer 2).

        Returns:
            Textual markup for the status line.
        """
        clock_style = "green" if work_running else "dim"
        clock = styled(f"⏱ Work: {format_duration(work_today)}", clock_style)
        focus_style = "cyan" if focus_seconds else "dim"
        focus = styled(f"▶ Focus: {format_duration(focus_seconds)}", focus_style)
        return f"{clock}    {focus}"


class KeyHintBar(Static):
    """Context-sensitive bottom key hints (newsboat-style key:Label strip).

    Two states, both rendered as a single line of ``key:Label`` cells:

    * *Idle* (:meth:`show_idle`) advertises the stream prefixes plus a curated
      subset of flat global keys, ending with ``?:Help`` and ``q:Quit``. The
      full key list lives in the help screens; the bar deliberately shows only
      a one-line subset.
    * *Domain* (:meth:`show_domain`) is painted when a stream prefix is
      pending: it shows ``<prefix> ›`` then each of that domain's sub-keys
      (resolved from the live keymap, so dynamic status keys appear), ending
      with ``?:Help`` and ``Esc:Cancel``.

    Like :class:`StatusLine` / :class:`TaskTimeLine` the rendering lives in
    pure, overridable ``format_*`` classmethods so a child theme can restyle
    the bar without reaching into the dispatcher or layout wiring.
    """

    #: The curated subset of flat global keys the idle bar advertises (the
    #: full set lives in help). Each entry is ``(key, label)``; kept as a
    #: class attribute so a child theme can tune the advertised set.
    IDLE_GLOBALS: tuple[tuple[str, str], ...] = (
        ("/", "Filter"),
        ("v", "View"),
        ("e", "Edit"),
        ("w", "Work"),
    )

    def show_idle(self, keymap: Any, globals_: Any = None) -> None:
        """Paint the idle/root bar advertising the stream prefixes + globals.

        Args:
            keymap: The ``KEYMAP`` mapping of prefix -> ``DomainSpec`` (used for
                each prefix's bar label).
            globals_: The curated ``(key, label)`` global cells; defaults to
                :attr:`IDLE_GLOBALS` when None.
        """
        self.update(self.format_idle(keymap, globals_))

    def show_domain(self, prefix: str, domain_spec: Any, entries: Any) -> None:
        """Paint the bar for a pending stream ``prefix``.

        Args:
            prefix: The pending prefix key (e.g. ``"s"``).
            domain_spec: The ``DomainSpec`` for the prefix (for its label).
            entries: The resolved ``KeyEntry`` rows for the domain.
        """
        self.update(self.format_domain(prefix, domain_spec, entries))

    @classmethod
    def format_idle(cls, keymap: Any, globals_: Any = None) -> str:
        """Return the idle-bar markup: stream prefixes + curated globals.

        Args:
            keymap: The ``KEYMAP`` mapping of prefix -> ``DomainSpec``.
            globals_: The curated ``(key, label)`` global cells; defaults to
                :attr:`IDLE_GLOBALS` when None.

        Returns:
            Textual markup for the one-line idle hint bar.
        """
        cells: list[str] = []
        for prefix, spec in keymap.items():
            cells.append(cls._cell(prefix, spec.label))
        for key, label in globals_ if globals_ is not None else cls.IDLE_GLOBALS:
            cells.append(cls._cell(key, label))
        cells.append(cls._cell("?", "Help"))
        cells.append(cls._cell("q", "Quit"))
        return "  ".join(cells)

    @classmethod
    def format_domain(cls, prefix: str, domain_spec: Any, entries: Any) -> str:
        """Return the domain-bar markup for a pending stream ``prefix``.

        Args:
            prefix: The pending prefix key (e.g. ``"s"``).
            domain_spec: The ``DomainSpec`` for the prefix (for its label).
            entries: The resolved ``KeyEntry`` rows for the domain.

        Returns:
            Textual markup for the one-line domain hint bar, ending with the
            ``?:Help`` and ``Esc:Cancel`` affordances.
        """
        head = styled(f"{prefix} ›", "bold")
        cells = [cls._cell(entry.key, entry.label) for entry in entries]
        tail = f"{cls._cell('?', 'Help')}  {cls._cell('Esc', 'Cancel')}"
        body = "  ".join(cells)
        return f"{head}  {body}     {tail}" if body else f"{head}     {tail}"

    @classmethod
    def _cell(cls, key: str, label: str) -> str:
        """Return one ``key:Label`` hint cell with the key accented.

        Args:
            key: The key glyph (e.g. ``"s"`` or ``"Esc"``).
            label: The human-readable label.

        Returns:
            Textual markup for a single hint cell.
        """
        return f"{styled(key, 'bold cyan')}:{label}"


class TaskTimeLine(Static):
    """Top-right elapsed-time display for the day's work and current task.

    Shows two values side by side:

    * the accumulated *total work time for the whole day* (summed across all of
      today's work-clock intervals), with the elapsed time of the *current
      work session* - the single currently-open work-clock interval - shown in
      parentheses after it (``Work: 2h30m (12m05s)``). The parenthetical is
      omitted when no session is open.
    * the total time spent on the *current task* - the task highlighted in the
      task list - summed across all of that task's worklogs.

    Like :class:`StatusLine` the rendering is a pure, overridable
    :meth:`format_times` classmethod so a child theme can replace it without
    reaching into layout or refresh wiring.
    """

    def update_times(
        self,
        work_today_seconds: int,
        session_seconds: int,
        session_running: bool,
        task_id: str | None,
        task_total_seconds: int,
    ) -> None:
        """Update the display with the day's work and per-task totals.

        Args:
            work_today_seconds: Accumulated total work seconds for the whole
                day (summed across all of today's work-clock intervals).
            session_seconds: Elapsed seconds of the current work session (the
                single currently-open work-clock interval; 0 when none).
            session_running: Whether a work session is currently open.
            task_id: The display id of the current (highlighted) task, or
                None when nothing is selected.
            task_total_seconds: Total seconds spent on the current task across
                all of its worklogs.
        """
        self.update(
            self.format_times(
                work_today_seconds,
                session_seconds,
                session_running,
                task_id,
                task_total_seconds,
            )
        )

    @classmethod
    def format_times(
        cls,
        work_today_seconds: int,
        session_seconds: int,
        session_running: bool,
        task_id: str | None,
        task_total_seconds: int,
    ) -> str:
        """Return the markup for the day's work + current-task elapsed display.

        Args:
            work_today_seconds: Accumulated total work seconds for the whole
                day (summed across all of today's work-clock intervals).
            session_seconds: Elapsed seconds of the current work session (the
                single currently-open work-clock interval; 0 when none).
            session_running: Whether a work session is currently open.
            task_id: The display id of the current (highlighted) task, or
                None when nothing is selected.
            task_total_seconds: Total seconds spent on the current task across
                all of its worklogs.

        Returns:
            Textual markup, right-aligned, showing the day's accumulated work
            time with the current session in parentheses, and the current
            task's total.
        """
        work_style = "green" if session_running else "dim"
        work_text = f"Work: {format_duration(work_today_seconds)}"
        if session_running:
            work_text += f" ({format_duration(session_seconds)})"
        work = styled(work_text, work_style)
        if task_id:
            label = f"{task_id}: {format_duration(task_total_seconds)}"
        else:
            label = "Task: -"
        task = styled(label, "magenta" if task_id else "dim")
        return f"{work}    {task}"


class AltLayoutView(TitleHighlight, VerticalScroll):
    """Shared base for the alternative task-list layout views.

    The default 3-pane :class:`TaskList` table is the structural layout;
    everything else (list / kanban / calendar) is an *alternative* layout that
    renders into the shared ``#alt-view`` container and is cycled with the
    ``v`` keybinding. This base declares the small contract the app relies on
    so :mod:`doxtr_doto.cli.tui.app` can drive every alt-view through one
    data-driven registry rather than per-layout branches, and so a single CSS
    selector (:class:`AltLayoutView`) styles any current or future view.

    Each view is a :class:`textual.containers.VerticalScroll` wrapping a single
    inner :class:`textual.widgets.Static` (``update_content`` writes the
    markup the ``format_*`` classmethods produce into it); that inner Static
    is built in :meth:`compose`, so it is a reserved seam - a subclass adding
    chrome around the view must ``yield from super().compose()`` (or otherwise
    preserve the inner content widget) rather than replace it, or
    :meth:`update_content` / :meth:`rendered_text` would have nothing to write
    to and the view would silently render nothing. Making the view a
    real scroll container - rather than a bare ``Static`` with
    ``overflow-y: auto`` - is what lets the content scroll at all: a plain
    ``Static`` never reports scrollable content, so once the cursor row went
    past the visible height the user could not see it. After every *continuous*
    (``j``/``k``) cursor move the view scrolls the highlighted row back into
    view via :meth:`scroll_to_cursor` (driven by the overridable
    :meth:`cursor_line`); after a *discontinuous* jump - a lane/column switch,
    a select-by-id, or a layout cycle that re-selects a task - the view
    repositions via :meth:`ensure_cursor_visible` instead, which guarantees the
    whole selected item is on screen without inferring a (now stale) move
    direction. (:class:`CalendarView` keeps its grid pinned either way; its day
    move / select-by-id reach their scroll through the subsequent rebuild.)

    The contract every subclass provides is:

    * :meth:`selected_id` - the id of the view's current selection (or None),
    * :meth:`rebuild` - repopulate the view from the current task set,
    * :meth:`move_cursor` - move the view's cursor by a signed delta
      (``j``/``k`` navigation), and
    * :meth:`cursor_line` - the 0-based content line the cursor occupies,
      overridable per view so :meth:`scroll_to_cursor` keeps the highlighted
      row visible; the base implementation keeps the view scrolled to the top.

    Individual views add view-specific affordances on top of this base:
    :class:`KanbanView` adds :meth:`~KanbanView.move_target_status` (the
    ``Tab``/``Shift+Tab`` card-move, a terminal drag-equivalent) and :class:`CalendarView` adds
    :meth:`~CalendarView.move_day` (``h``/``l`` day navigation). Those stay
    view-specific and are dispatched by the app only for their layout.
    """

    #: Alt-views are keyboard-navigable, so they must accept focus.
    can_focus = True

    #: How many rows from the top/bottom edge of the visible task frame the
    #: cursor must come before :meth:`scroll_to_cursor` starts scrolling. While
    #: the cursor stays further than this many rows from either edge the view
    #: does not scroll at all (so navigation does not creep line-by-line); once
    #: the cursor comes within ``SCROLL_MARGIN`` rows of an edge the view jumps
    #: (see :attr:`SCROLL_JUMP`). Overridable per view / by a child theme (a
    #: class attribute) so the trigger distance can be tuned without touching
    #: :meth:`scroll_to_cursor`.
    SCROLL_MARGIN: int = 2

    #: How many *extra* tasks past the margin trigger :meth:`scroll_to_cursor`
    #: jumps in the direction the cursor is moving, so navigation hops a block
    #: of rows at a time rather than one line. Overridable per view / by a
    #: child theme (a class attribute).
    SCROLL_JUMP: int = 5

    #: Rebind the arrow keys to the view's navigation actions.
    #:
    #: :class:`~textual.containers.VerticalScroll` binds ``up``/``down``/
    #: ``left``/``right`` to its own scroll actions, which - because a focused
    #: widget's bindings take priority over the app's - would otherwise
    #: hijack the arrow keys and merely scroll the container instead of moving
    #: the view's cursor. These bindings override that so the arrows mirror
    #: the vim keys on every layout (Bug 1): up/down move the cursor and
    #: left/right drive the layout move (kanban column / calendar day),
    #: delegating to the app actions so the behavior matches ``j``/``k`` and
    #: ``h``/``l`` exactly. The view still scrolls to follow the cursor via
    #: :meth:`scroll_to_cursor`.
    #:
    #: ``tab``/``shift+tab`` are likewise rebound to the app's pane-cycle
    #: actions: Textual's default screen-level focus navigation would otherwise
    #: consume ``tab`` (and ``shift+tab``) on the focused view before the
    #: app's ``cycle_pane`` / ``cycle_pane_reverse`` binding fires, so Tab
    #: could never advance from the alt-view into the details pane and
    #: Shift+Tab could never reverse that cycle (Feature 1). Delegating keeps
    #: the kanban card-move cycle and the calendar region/details cycle (and
    #: their Shift+Tab reverse) under the app's control.
    BINDINGS = [
        ("up", "nav_cursor_up", "Up"),
        ("down", "nav_cursor_down", "Down"),
        # Jump-to-edge navigation. Like the up/down bindings above these must
        # be re-bound on the focused view (not left to the app) because a
        # focused widget's bindings take priority over the app's, so the
        # app-level ``shift+up`` / ``shift+down`` would never fire while an
        # alt-view holds focus. Both delegate straight to the app's jump
        # actions so the behavior matches the TABLE layout exactly.
        ("shift+up", "nav_cursor_top", "Jump to top"),
        ("shift+down", "nav_cursor_bottom", "Jump to bottom"),
        ("left", "nav_layout_prev", "Prev column/day"),
        ("right", "nav_layout_next", "Next column/day"),
        ("tab", "nav_cycle_pane", "Cycle pane"),
        # Bind both ``shift+tab`` and ``back_tab``: some terminals deliver the
        # physical Shift+Tab as the literal ``back_tab`` key, so reverse
        # cycling must match either name while a view holds focus (see
        # DotoApp.BINDINGS). Both route to the same reverse action.
        ("shift+tab", "nav_cycle_pane_reverse", "Cycle pane (reverse)"),
        ("back_tab", "nav_cycle_pane_reverse", "Cycle pane (reverse)"),
    ]

    def action_nav_cycle_pane(self) -> None:
        """Cycle panes forward for the active layout (Tab -> app action)."""
        cast("DotoApp", self.app).action_cycle_pane()

    def action_nav_cycle_pane_reverse(self) -> None:
        """Cycle panes in reverse (Shift+Tab -> app action)."""
        cast("DotoApp", self.app).action_cycle_pane_reverse()

    def action_nav_cursor_up(self) -> None:
        """Move the active layout's cursor up (arrow key -> app action)."""
        cast("DotoApp", self.app).action_cursor_up()

    def action_nav_cursor_down(self) -> None:
        """Move the active layout's cursor down (arrow key -> app action)."""
        cast("DotoApp", self.app).action_cursor_down()

    def action_nav_cursor_top(self) -> None:
        """Jump to the first entry (Shift+Up -> app action)."""
        cast("DotoApp", self.app).action_cursor_top()

    def action_nav_cursor_bottom(self) -> None:
        """Jump to the last entry (Shift+Down -> app action)."""
        cast("DotoApp", self.app).action_cursor_bottom()

    def action_nav_layout_prev(self) -> None:
        """Move left in the active layout (arrow key -> app action)."""
        cast("DotoApp", self.app).action_layout_move_prev()

    def action_nav_layout_next(self) -> None:
        """Move right in the active layout (arrow key -> app action)."""
        cast("DotoApp", self.app).action_layout_move_next()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the scroll container and its (unmounted) content state."""
        super().__init__(*args, **kwargs)
        #: The inner Static rendering the view markup; created in
        #: :meth:`compose`, so None until the view is mounted.
        self._content: Static | None = None
        #: The most recent markup, cached so a pre-mount ``rebuild`` still
        #: shows once :meth:`compose` creates :attr:`_content`.
        self._pending_markup: str = ""
        #: The cursor's content line at the previous :meth:`scroll_to_cursor`
        #: call, used to infer the move direction so the smart-scroll jump
        #: (:attr:`SCROLL_JUMP`) hops the right way. Starts at 0. A subclass
        #: that relocates the cursor *discontinuously* (e.g. a rebuild that
        #: snaps the cursor to the top or to a preserved id) must re-anchor
        #: this to the post-rebuild line via :meth:`_sync_scroll_anchor` so
        #: the next move's direction is inferred relative to where the cursor
        #: actually landed, not where it was before the rebuild.
        self._last_cursor_line: int = 0

    def compose(self) -> ComposeResult:
        """Build the single inner :class:`Static` that holds the view markup.

        This inner Static is the widget :meth:`update_content` /
        :meth:`rendered_text` read and write, so it is a reserved seam: a
        subclass overriding :meth:`compose` to add chrome must
        ``yield from super().compose()`` (or otherwise keep the inner content
        Static) rather than replace it, or the view would render nothing.
        """
        self._content = Static()
        self._content.update(self._pending_markup)
        yield self._content

    def update_content(self, markup: str) -> None:
        """Write the view's rendered markup into the inner Static.

        Replaces the former ``self.update(...)`` call: because the view is now
        a scroll container, its own ``render`` no longer draws text; the markup
        the ``format_*`` classmethods produce is shown by the inner Static
        instead. The markup is cached so a ``rebuild`` that runs before the
        view is mounted (e.g. the pure-logic unit tests that construct a view
        directly) is applied once :meth:`compose` creates the Static.

        Args:
            markup: The Textual markup produced by the view's ``format_*``
                classmethods.
        """
        self._pending_markup = markup
        if self._content is not None:
            self._content.update(markup)

    def rendered_text(self) -> str:
        """Return the view's current rendered markup as text.

        A small helper so callers (and tests) can inspect what the view shows
        without reaching into the inner widget, now that the view itself is a
        container rather than the rendering ``Static``. Before the view is
        mounted it returns the pending markup string directly.

        Returns:
            The inner Static's rendered content (or the pending markup when the
            view is not yet mounted) as a string.
        """
        if self._content is None:
            return self._pending_markup
        return str(self._content.render())

    def cursor_line(self) -> int:
        """Return the 0-based content line the cursor currently occupies.

        Overridable per view (list/kanban/calendar track the cursor
        differently) so :meth:`scroll_to_cursor` can keep the highlighted row
        visible. The base implementation keeps the view scrolled to the top.

        Returns:
            The content line index to keep in view (0 by default).
        """
        return 0

    def cursor_span(self) -> int:
        """Return how many content lines the highlighted item occupies.

        The per-view *height* of the cursor item, so the shared smart-scroll
        algorithm (:meth:`target_scroll_y`) can keep the **whole** selected
        item on screen rather than only its top line (:meth:`cursor_line`).
        For the plain list every task is a single content line, so the base
        implementation returns ``1``. :class:`KanbanView` overrides this to
        return the full card height because each card is a fixed, multi-line
        block. (:class:`CalendarView` does not use the shared scroll path at
        all - it overrides :meth:`scroll_to_cursor` - so its behavior is
        preserved regardless of this value.) Overridable per view / by a child
        theme so the scroll feel can be retuned alongside
        :attr:`SCROLL_MARGIN` / :attr:`SCROLL_JUMP` / :meth:`target_scroll_y`.

        Returns:
            The number of content lines the cursor item spans (>= 1).
        """
        return 1

    def scroll_to_cursor(self) -> None:
        """Scroll so the cursor's content line (:meth:`cursor_line`) is visible.

        Called after :meth:`rebuild` / :meth:`move_cursor` so a cursor moving
        past the visible height follows into view rather than disappearing. A
        no-op until the view is mounted (no region to scroll yet).

        Uses the shared *smart scrolling* algorithm (:meth:`target_scroll_y`):
        the view only scrolls once the cursor comes within
        :attr:`SCROLL_MARGIN` rows of the top or bottom edge of the visible
        frame, and when it does it jumps :attr:`SCROLL_JUMP` extra tasks in
        the move direction so navigation hops a block at a time rather than
        creeping one line. Both the margin and the jump are overridable class
        attributes so a child theme can tune the feel. When the content fits
        the frame there is nothing to scroll and the view stays put.
        """
        if not self.is_mounted:
            return
        cursor = self.cursor_line()
        target = self.target_scroll_y(cursor, self._last_cursor_line)
        self._last_cursor_line = cursor
        if target is not None:
            self.scroll_to(y=target, animate=False)

    def _sync_scroll_anchor(self) -> None:
        """Re-anchor the scroll-direction baseline to the current cursor line.

        Sets :attr:`_last_cursor_line` to the current :meth:`cursor_line` so
        the *next* :meth:`scroll_to_cursor` infers its move direction relative
        to where the cursor is now, not where it was before.

        The scroll-direction contract (see :attr:`_last_cursor_line` /
        :meth:`target_scroll_y`): :attr:`_last_cursor_line` must track the
        cursor's content line as of the last scroll decision. :meth:`rebuild`
        can move the cursor *discontinuously* - it is preserved by id, snapped
        to the top, or clamped into range - which is not a navigation move, so
        a subclass calls this at the end of :meth:`rebuild` (right before
        :meth:`scroll_to_cursor`) to reset the baseline. Without it a rebuild
        that relocates the cursor would make the first subsequent ``j``/``k``
        infer a bogus direction from a stale pre-rebuild line and jump the
        wrong way.
        """
        self._last_cursor_line = self.cursor_line()

    def scroll_cursor_to_edge(self, to_bottom: bool) -> None:
        """Scroll so a *discontinuous* jump to the first / last entry lands.

        The scroll counterpart of :meth:`move_cursor_to_edge` for the views
        that follow the shared smart-scroll path (list / kanban). Unlike
        :meth:`scroll_to_cursor`, it does **not** infer the move direction
        from :attr:`_last_cursor_line` - a jump to an edge is discontinuous
        and its direction is already known from ``to_bottom`` - so it scrolls
        straight to the content edge the jump targets:

        * ``to_bottom=False`` (jump to top) scrolls to offset ``0`` so the
          first entry sits at the top of the frame;
        * ``to_bottom=True`` (jump to bottom) scrolls to :attr:`max_scroll_y`
          so the last entry sits at the bottom of the frame.

        This fixes the bug where jumping to the bottom and then back to the
        top left the frame stuck at the bottom: :meth:`scroll_to_cursor`
        re-anchored :attr:`_last_cursor_line` to the landing line first, so
        ``target_scroll_y`` saw ``cursor_line == previous_line``, inferred a
        *downward* move (the ``>=`` tie-break) and never took the
        snap-to-top branch (which is gated on ``not moving_down``). Scrolling
        directly to the known edge sidesteps the direction inference entirely.

        The smart-scroll baseline is re-anchored to the landing line
        afterwards so the next ``j``/``k`` navigation infers its direction
        from where the cursor actually is. A no-op until the view is mounted.

        Args:
            to_bottom: Jump to the last entry when True, the first when False.
        """
        self._last_cursor_line = self.cursor_line()
        if not self.is_mounted:
            return
        target = self.max_scroll_y if to_bottom else 0
        self.scroll_to(y=target, animate=False)

    def ensure_cursor_visible(self) -> None:
        """Reposition the viewport so the *whole* cursor item is on screen.

        The discontinuous-jump counterpart of :meth:`scroll_to_cursor` /
        :meth:`scroll_cursor_to_edge` for the views that follow the shared
        smart-scroll path (list / kanban). Where :meth:`scroll_to_cursor`
        *infers* the move direction from :attr:`_last_cursor_line` (correct for
        continuous ``j``/``k`` navigation, where the cursor steps one row at a
        time), this method makes **no** direction assumption: it guarantees the
        full cursor span ``[cursor_line .. cursor_line + span - 1]`` is visible
        regardless of where the cursor was before.

        That difference is the whole point of this seam. After a *discontinuous*
        selection change - switching kanban swim lanes (via
        :meth:`DotoApp._kanban_navigate` after the rebuild), selecting a task
        by id (:meth:`select_id`), or a layout switch that re-selects a task
        (:meth:`DotoApp._cycle_layout`) - the cursor can land arbitrarily far
        from where it was, so the stale direction baseline makes
        :meth:`scroll_to_cursor` take the wrong branch (or no branch) and leave
        the selected item off screen. Example: the cursor is at the bottom of a
        long ``open`` lane and the user switches to a one-card ``in-progress``
        lane whose single card is at the top; :meth:`target_scroll_y` infers a
        stale *downward* direction and does not scroll, so the selected card is
        not visible. Repositioning here with no direction inference fixes that.

        The target reuses the same clamp logic as :meth:`target_scroll_y` so a
        whole multi-line item (a kanban card) is kept fully in view:

        * the cursor item occupies ``[cursor_line .. item_bottom]`` where
          ``item_bottom = cursor_line + span - 1`` and ``span`` is
          :meth:`cursor_span`;
        * an item that fits the frame is kept on screen with **minimal**
          scroll: the offset is clamped into
          ``[item_bottom - height + 1 .. cursor_line]`` - the deepest offset
          that still shows the item's bottom, and the shallowest that still
          shows its top - starting from the *current* :attr:`scroll_y`, so an
          item that is already fully visible does not move the frame at all;
        * an oversized item (``span > height``, impossible to fit) aligns its
          *top* to the viewport top so the user sees the start of the item,
          mirroring :meth:`target_scroll_y`'s oversized-card branch.

        The smart-scroll baseline (:attr:`_last_cursor_line`) is re-anchored to
        the landing line afterwards - like :meth:`scroll_cursor_to_edge` - so
        the next ``j``/``k`` navigation infers its direction from where the
        cursor actually is, not from the pre-jump line. A no-op until the view
        is mounted (no region to reposition yet).

        An overridable seam - like :meth:`scroll_to_cursor` /
        :meth:`target_scroll_y` - so a child theme can retune or replace the
        reposition behavior by subclassing and swapping the matching
        ``*_view_class`` app attribute. :class:`CalendarView` overrides it to
        stay consistent with its pinned-grid :meth:`scroll_to_cursor`.
        """
        self._last_cursor_line = self.cursor_line()
        if not self.is_mounted:
            return
        target = self.target_visible_scroll_y(self.cursor_line())
        if target is not None:
            self.scroll_to(y=target, animate=False)

    def _clamp_span_onto_screen(
        self,
        cursor_line: int,
        span: int,
        height: int,
        start: int,
        max_scroll: int,
    ) -> int:
        """Clamp a scroll offset so the whole cursor span stays on screen.

        The shared whole-item clamp used by both scroll paths
        (:meth:`target_scroll_y`'s multi-line branch and
        :meth:`target_visible_scroll_y`), so the subtle, retune-prone geometry
        lives in one place:

        * ``lo = item_bottom - height + 1`` is the deepest offset that still
          shows the item's bottom; ``hi = cursor_line`` is the shallowest that
          still shows its top, so ``lo <= offset <= hi`` keeps every line of
          the span ``[cursor_line .. cursor_line + span - 1]`` visible;
        * ``start`` is clamped into ``[lo, hi]`` and then into the scrollable
          range ``[0, max_scroll]`` - the caller passes the offset the clamp
          should start from (``target_scroll_y`` its computed jump target,
          ``target_visible_scroll_y`` the current :attr:`scroll_y` for minimal
          movement);
        * an oversized span (``span > height``) cannot fit, so the item's top
          is aligned to the viewport top (``cursor_line``) to show its start.

        Args:
            cursor_line: The cursor's current 0-based content line (the top
                line of the cursor item).
            span: The cursor item's line span (``>= 1``).
            height: The viewport height in lines.
            start: The offset the clamp starts from before being pinned into
                the visible range.
            max_scroll: The maximum scrollable offset (``max_scroll_y``).

        Returns:
            The content-line offset that keeps the whole span on screen.
        """
        item_bottom = cursor_line + span - 1
        if span > height:
            # Oversized item: align its top to the viewport top (show its
            # start) rather than pushing it off either edge.
            target = cursor_line
        else:
            lo = item_bottom - height + 1
            hi = cursor_line
            target = min(max(start, lo), hi)
        return max(0, min(max_scroll, target))

    def target_visible_scroll_y(self, cursor_line: int) -> int | None:
        """Return the offset that keeps the whole cursor span visible, or None.

        The pure (modulo the mounted viewport geometry it reads) target
        computation behind :meth:`ensure_cursor_visible`: unlike
        :meth:`target_scroll_y` it takes no ``previous_line`` and infers no
        move direction - it only guarantees the full cursor span
        ``[cursor_line .. cursor_line + span - 1]`` is on screen with the
        smallest possible scroll from the current :attr:`scroll_y`.

        The clamp mirrors :meth:`target_scroll_y` - both delegate to the
        shared :meth:`_clamp_span_onto_screen`:

        * ``lo = item_bottom - height + 1`` puts the item's bottom at the
          bottom edge; ``hi = cursor_line`` puts its top at the top edge, so
          ``lo <= offset <= hi`` keeps every line of the span visible;
        * the current :attr:`scroll_y` is clamped into ``[lo, hi]`` (so an item
          already fully visible returns None - no move), then clamped to the
          scrollable range ``[0, max_scroll_y]``;
        * an oversized span (``span > height``) cannot fit, so the item's top
          is aligned to the viewport top (``cursor_line``) to show its start.

        Factored out of :meth:`ensure_cursor_visible` so the reposition target
        can be unit-tested without a live terminal (the same way
        :meth:`target_scroll_y` is) and overridden independently of the scroll
        call. Overridable per view / by a child theme.

        Args:
            cursor_line: The cursor's current 0-based content line (the top
                line of the cursor item).

        Returns:
            The content-line offset to scroll the top of the viewport to, or
            None when the whole span is already visible (no scroll needed).
        """
        max_scroll = self.max_scroll_y
        if max_scroll <= 0:
            return None
        height = self.size.height
        if height <= 0:
            return None
        span = max(1, self.cursor_span())
        current = int(self.scroll_y)
        # Minimal scroll: start the clamp from the current offset so an item
        # that is already fully visible stays put (``target == current``).
        target = self._clamp_span_onto_screen(
            cursor_line, span, height, start=current, max_scroll=max_scroll
        )
        if target == current:
            return None
        return target

    def target_scroll_y(self, cursor_line: int, previous_line: int) -> int | None:
        """Return the smart-scroll target offset, or None to stay put.

        The shared, pure (modulo the mounted viewport geometry it reads)
        smart-scrolling algorithm used by every scrollable alt-view:

        * while the cursor item stays more than :attr:`SCROLL_MARGIN` rows
          from both the top and bottom edges of the current viewport the view
          does not scroll (returns None), so navigation in the middle of the
          frame does not creep line-by-line;
        * once the cursor item comes within :attr:`SCROLL_MARGIN` rows of an
          edge *in the direction it is moving* the view scrolls so the whole
          item jumps :attr:`SCROLL_JUMP` extra rows past that edge, hopping a
          block of rows at a time. The trigger is gated on the move direction
          (inferred from ``previous_line``): a move that lands within the
          bottom margin while heading up (or within the top margin while
          heading down) does not snap the frame against the move direction -
          it falls through to None;
        * the cursor item is treated as occupying the full line span returned
          by :meth:`cursor_span` (one line for the plain list, a whole card
          height for kanban), so the test and the computed target keep the
          **entire** highlighted item on screen rather than only its top line.
          For the common one-line list this is identical to the previous
          single-line behavior;
        * the result is clamped to the scrollable range so it never scrolls
          past the content, and the final clamp guarantees the whole span
          fits when it can. When a single item is *taller* than the viewport
          (``span > height``) that is impossible, so the move-down path
          deliberately aligns the item's **top** to the viewport top (the
          user sees the start of the oversized card) rather than pushing it
          fully off the bottom.

        Overriding :attr:`SCROLL_MARGIN` / :attr:`SCROLL_JUMP` /
        :meth:`cursor_span` (or this method) lets a child theme or a specific
        view tune the behavior.

        Args:
            cursor_line: The cursor's current 0-based content line (the top
                line of the cursor item).
            previous_line: The cursor's content line before this move, used to
                infer the scroll direction.

        Returns:
            The content-line offset to scroll the top of the viewport to, or
            None when no scroll is needed.
        """
        max_scroll = self.max_scroll_y
        if max_scroll <= 0:
            return None
        top = int(self.scroll_y)
        height = self.size.height
        if height <= 0:
            return None
        bottom = top + height - 1
        margin = self.SCROLL_MARGIN
        span = max(1, self.cursor_span())
        # The cursor item occupies lines [cursor_line .. item_bottom].
        item_bottom = cursor_line + span - 1
        moving_down = cursor_line >= previous_line
        if moving_down and item_bottom > bottom - margin:
            # Moving down into (or past) the bottom edge: jump so the whole
            # item sits a block above the new bottom edge. The jump is driven
            # by the item's *bottom* (so a tall card is pulled fully into
            # view), not just its top line. Gated on ``moving_down`` so a
            # move that is within the bottom margin but heading *up* does not
            # snap the frame downward against the move direction.
            target = item_bottom - height + 1 + self.SCROLL_JUMP
        elif not moving_down and cursor_line < top + margin:
            # Moving up into (or past) the top edge: jump so the item's top
            # sits a block below the new top edge. Gated on ``not moving_down``
            # for the symmetric reason - a within-top-margin move heading
            # *down* must not snap the frame upward against the move direction.
            target = cursor_line - self.SCROLL_JUMP
        else:
            return None
        # Guarantee the whole span is visible when it can be. The multi-line
        # and oversized branches share the same clamp as the discontinuous
        # reposition via :meth:`_clamp_span_onto_screen` (lo = item bottom at
        # the bottom edge, hi = item top at the top edge, oversized aligns the
        # top), starting from the computed jump ``target`` so the SCROLL_JUMP
        # look-ahead is preserved where it still fits. The one-line branch is
        # kept separate: lo == hi there would defeat the look-ahead.
        if span == 1:
            # One-line list / calendar: the item is a single line so lo == hi
            # (both equal ``cursor_line``) would defeat the SCROLL_JUMP
            # look-ahead. Preserve the original single-line nudge instead - the
            # target may legitimately scroll the lone cursor line toward the
            # edge it is moving away from.
            if moving_down:
                target = max(target, cursor_line - height + 1)
            else:
                target = min(target, cursor_line)
            return max(0, min(max_scroll, target))
        return self._clamp_span_onto_screen(
            cursor_line, span, height, start=target, max_scroll=max_scroll
        )

    def selected_id(self) -> str | None:
        """Return the id of the view's current selection, or None.

        Returns:
            The selected task id, or None when nothing is selectable.
        """
        raise NotImplementedError

    def rebuild(self, tasks: list[dict[str, Any]]) -> None:
        """Repopulate the view from the current task set.

        Args:
            tasks: Task dicts (as produced by
                :func:`doxtr_doto.cli.tui.data.gather_tasks`).
        """
        raise NotImplementedError

    def move_cursor(self, delta: int) -> None:
        """Move the view's cursor by ``delta`` (``j``/``k`` navigation).

        Args:
            delta: Rows to move (negative moves up).
        """
        raise NotImplementedError

    def move_cursor_to_edge(self, to_bottom: bool) -> None:
        """Jump the view's cursor to the first or last entry.

        The jump-to-edge counterpart of :meth:`move_cursor`, bound to
        ``Shift+Up`` / ``Shift+Down`` and driven by the app's
        :meth:`~doxtr_doto.cli.tui.app.DotoApp._jump_cursor`. Each view sets
        its cursor index directly to the first / last valid entry (rather than
        moving by a large delta) and then scrolls so the landing row is
        visible, re-anchoring the smart-scroll baseline where a discontinuous
        jump needs it (:meth:`_sync_scroll_anchor`). An overridable seam - like
        :meth:`move_cursor` - so a child theme can retune or replace the
        jump per view by subclassing and swapping the ``*_view_class`` app
        attribute.

        Args:
            to_bottom: Jump to the last entry when True, the first when False.
        """
        raise NotImplementedError

    def select_id(self, task_id: str) -> bool:
        """Move the view's cursor to the row for ``task_id``, if present.

        The task-selection counterpart of :meth:`move_cursor` /
        :meth:`move_cursor_to_edge`: instead of stepping or jumping to an edge
        it places the cursor on the row whose *display* id equals ``task_id``
        and scrolls it into view, reusing each view's existing cursor-move /
        smart-scroll path rather than inventing new scrolling. It backs the
        app-level :meth:`~doxtr_doto.cli.tui.app.DotoApp.select_task` seam used
        to reveal a freshly added task
        (:meth:`~doxtr_doto.cli.tui.app.DotoApp.action_add`).

        The base implementation returns ``False`` (no task matched / this view
        does not select by task id): :class:`TimeView`, whose selection keys on
        a *day* rather than a task, deliberately inherits this no-op so an
        auto-select request there is simply ignored. The task-centric views
        (:class:`TaskList`, :class:`ListView`, :class:`KanbanView`,
        :class:`CalendarView`) override it. An overridable seam so a child
        theme can retune or replace the per-view selection by subclassing and
        swapping the matching ``*_view_class`` / ``task_list_class`` app
        attribute; keep the id-preservation behavior in :meth:`rebuild` intact.

        Args:
            task_id: The *display* id (bare or namespaced) to select.

        Returns:
            True when a matching row was found and the cursor moved to it,
            False otherwise.
        """
        return False


class ListView(TreePrefixMixin, AltLayoutView):
    """Single-column list view: one task per line, Enter reveals details.

    This is the ``list`` TUI layout (:attr:`doxtr_doto.enums.TuiLayout.LIST`):
    an alternative to the default table that shows every task on one compact
    line. The currently highlighted row is tracked by index in
    :attr:`cursor` so ``j``/``k`` can move through the list, and
    :meth:`selected_id` resolves the cursor to a task id. Activating a row
    with ``Enter`` reveals that task's details - the requirement's
    "Enter-to-detail" behavior - by refreshing and focusing the same
    :class:`TaskDetails` pane used by the table layout; that activation is an
    app action (``action_activate``) rather than widget business logic.

    Rendering is delegated to the pure, overridable :meth:`format_line` /
    :meth:`format_lines` classmethods so a child theme can replace the
    per-line markup by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.list_view_class`.
    """

    #: Fallback content width used when the view's own
    #: ``scrollable_content_region`` is not yet known (pre-mount). Mirrors
    #: :class:`KanbanView`'s ``DEFAULT_COLUMN_WIDTH`` convention so the
    #: wrap-aware :meth:`cursor_line` has a sane width to measure against
    #: before the first layout pass.
    DEFAULT_CONTENT_WIDTH: int = 80

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the list view with empty rows and a zeroed cursor."""
        super().__init__(*args, **kwargs)
        self.row_ids: list[str] = []
        self.cursor: int = 0
        #: The per-row rendered markup, cached by the most recent
        #: :meth:`rebuild` so :meth:`cursor_line` can measure each row's
        #: *wrapped* display height (a long title wraps to several display
        #: lines) without re-rendering the whole list on every keypress. One
        #: entry per ``row_ids`` entry, in the same order.
        self._row_markup: list[str] = []

    def rebuild(self, tasks: list[dict[str, Any]], collapsed_ids: set[str] | None = None) -> None:
        """Rebuild the list from task dicts, nesting sub-tasks as a tree.

        Mirrors :meth:`TaskList.rebuild`: the visible list is flattened into a
        depth-first pre-order parent/child tree via
        :func:`doxtr_doto.cli.tui.filtersort.flatten_tree`, so each sub-task is
        drawn indented under its ``parent`` with an expand/collapse triangle,
        and the cursor is preserved by id across rebuilds. ``tasks`` is
        consumed in the order the caller's view pipeline produced it (already
        active-pinned via :func:`pin_active_first`, Feature A); this method
        does not re-pin.

        Args:
            tasks: Task dicts (as produced by
                :func:`doxtr_doto.cli.tui.data.gather_tasks`).
            collapsed_ids: The set of parent ids whose children are hidden
                (default-expanded otherwise). None is treated as empty.
        """
        previous = self.selected_id()
        # ``tasks`` is already active-pinned by the caller's view pipeline
        # (pin_active_first, Feature A); consume that order as-is rather than
        # re-pinning here. Flatten into the parent/child tree so sub-tasks
        # nest under their parent.
        rows = flatten_tree(tasks, collapsed_ids)
        self.row_ids = [str(row.task.get("id", "")) for row in rows]
        if previous is not None and previous in self.row_ids:
            self.cursor = self.row_ids.index(previous)
        else:
            self.cursor = min(self.cursor, max(len(self.row_ids) - 1, 0))
        # Cache each row's markup so cursor_line can measure wrapped heights.
        # format_line is called without the cursor highlight because the
        # highlight wrapper does not change the line's rendered width/height.
        self._row_markup = [self.format_line(row, False) for row in rows]
        self.update_content(self.format_lines(rows, self.cursor))
        self._sync_scroll_anchor()
        self.scroll_to_cursor()

    def selected_id(self) -> str | None:
        """Return the id of the currently highlighted row.

        Returns:
            The highlighted row's id, or None when the list is empty.
        """
        if not self.row_ids:
            return None
        if self.cursor < 0 or self.cursor >= len(self.row_ids):
            return None
        return self.row_ids[self.cursor]

    def move_cursor(self, delta: int) -> None:
        """Move the highlighted row by ``delta`` (clamped to the list bounds).

        Args:
            delta: Number of rows to move (negative moves up).
        """
        if not self.row_ids:
            return
        self.cursor = max(0, min(len(self.row_ids) - 1, self.cursor + delta))
        self.scroll_to_cursor()

    def move_cursor_to_edge(self, to_bottom: bool) -> None:
        """Jump the highlighted row to the first / last entry (``Shift+Up``/down).

        Snaps :attr:`cursor` to ``0`` (top) or the last row (bottom) rather
        than stepping, then scrolls straight to the matching content edge
        (:meth:`~AltLayoutView.scroll_cursor_to_edge`) so the discontinuous
        jump lands correctly in both directions instead of inferring a bogus
        direction from the pre-jump line. A no-op on an empty list.

        Args:
            to_bottom: Jump to the last row when True, the first when False.
        """
        if not self.row_ids:
            return
        self.cursor = len(self.row_ids) - 1 if to_bottom else 0
        self.scroll_cursor_to_edge(to_bottom)

    def select_id(self, task_id: str) -> bool:
        """Place the cursor on the row whose id equals ``task_id``.

        Sets :attr:`cursor` to the matching row index and repositions it into
        view via the discontinuous :meth:`~AltLayoutView.ensure_cursor_visible`
        path (selecting by id is a jump, not a step, so the direction-inferring
        :meth:`~AltLayoutView.scroll_to_cursor` could leave it off screen).
        See :meth:`AltLayoutView.select_id` for the overall contract.

        Args:
            task_id: The display id (bare or namespaced) to select.

        Returns:
            True when ``task_id`` is a current row and the cursor moved to it,
            False when it is not present.
        """
        if task_id not in self.row_ids:
            return False
        self.cursor = self.row_ids.index(task_id)
        self.ensure_cursor_visible()
        return True

    def _content_width(self) -> int:
        """Return the width (screen columns) rows wrap to, or a safe fallback.

        The inner Static renders into the scroll container's content region,
        so a row longer than this width wraps to several display lines. The
        width is only known once the view is mounted and laid out; before that
        (e.g. the pure-logic unit tests that construct a view directly) this
        falls back to :attr:`DEFAULT_CONTENT_WIDTH`.

        Returns:
            The content width in screen columns (always >= 1).
        """
        if self.is_mounted:
            width = self.scrollable_content_region.width
            if width > 0:
                return width
        return self.DEFAULT_CONTENT_WIDTH

    def row_height(self, markup: str, width: int) -> int:
        """Return how many display lines one row's ``markup`` wraps to.

        A row is nominally one compact line, but a long title wraps to several
        display lines when it exceeds the content width - and the smart-scroll
        algorithm (:meth:`~AltLayoutView.scroll_to_cursor`) tracks *display*
        lines, not task indices. Measuring the wrapped height here (mirroring
        :meth:`KanbanView.card_height`) is what keeps :meth:`cursor_line`
        honest so the highlighted row never scrolls out of the view pane.

        Args:
            markup: The row's Textual markup (as :meth:`format_line` produces).
            width: The content width (screen columns) the row wraps to.

        Returns:
            The number of display lines the row occupies (always >= 1).
        """
        if width <= 0:
            return 1
        text = _Text.from_markup(markup)
        return max(1, len(text.wrap(_MEASURE_CONSOLE, width)))

    def cursor_line(self) -> int:
        """Return the display line the highlighted row starts on.

        A row is nominally one compact line, so historically this returned the
        cursor index directly. But when a row's title is long enough to wrap,
        each row above the cursor occupies *more than one* display line, so the
        cursor's true display line is the sum of the wrapped heights
        (:meth:`row_height`) of every row above it - not its index. Returning
        the index in that case made :meth:`~AltLayoutView.scroll_to_cursor`
        keep the wrong (too-shallow) line in view, so the highlighted row
        scrolled out of the visible pane. Summing the real heights keeps
        scroll-follow landing on the highlighted row even when earlier rows
        wrapped.

        Returns:
            The highlighted row's 0-based starting display line.
        """
        width = self._content_width()
        line = 0
        for index in range(min(self.cursor, len(self._row_markup))):
            line += self.row_height(self._row_markup[index], width)
        return line

    @classmethod
    def format_lines(cls, rows: Sequence[TreeRow | dict[str, Any]], cursor: int) -> str:
        """Return the full list markup, highlighting the cursor row.

        Args:
            rows: The rows to render - either
                :class:`~doxtr_doto.cli.tui.filtersort.TreeRow` objects (the
                tree-aware path :meth:`rebuild` uses) or bare task dicts (for
                pure-logic callers/tests).
            cursor: The index of the highlighted row.

        Returns:
            Textual markup for the whole list (an empty-state line when there
            are no tasks).
        """
        if not rows:
            return "[dim]No tasks.[/dim]"
        lines = [cls.format_line(row, index == cursor) for index, row in enumerate(rows)]
        return "\n".join(lines)

    @classmethod
    def format_line(cls, row: TreeRow | dict[str, Any], highlighted: bool) -> str:
        """Return one task's single-line markup.

        Accepts either a :class:`~doxtr_doto.cli.tui.filtersort.TreeRow`
        (carrying depth / expansion for the tree prefix) or a bare task dict
        (treated as a depth-0 leaf). The line is prefixed with the
        expand/collapse triangle + depth indent from :meth:`format_tree_prefix`
        so sub-tasks read as an indented tree, mirroring :meth:`TaskList`.

        Args:
            row: A :class:`TreeRow` or a bare task dict.
            highlighted: Whether this row is under the cursor.

        Returns:
            Textual markup for the task's line.
        """
        if isinstance(row, TreeRow):
            task = row.task
            depth, has_children, expanded = row.depth, row.has_children, row.expanded
        else:
            task = row
            depth, has_children, expanded = 0, False, False
        running = "[green]\u25b6[/green]" if task.get("_running") else " "
        done = task.get("status") == DONE_STATUS
        checkbox = "[dim]\\[\u2713][/dim]" if done else "\\[ ]"
        priority = task.get("priority") or ""
        pri_cell = styled((priority[:4] or "-").ljust(4), priority_style(priority))
        status = task.get("status") or ""
        status_cell = styled((status or "-"), status_style(status))
        task_id = escape_markup(task.get("id", ""))
        prefix = cls.format_tree_prefix(depth, has_children, expanded)
        title = prefix + cls.escape_title(task.get("title", ""))
        line = f"{running} {checkbox} {pri_cell} {status_cell} [bold]{task_id}[/bold]  {title}"
        if highlighted:
            return f"[reverse]{line}[/reverse]"
        return line


class KanbanView(AltLayoutView):
    """Kanban view: tasks grouped into columns by status.

    This is the ``kanban`` TUI layout
    (:attr:`doxtr_doto.enums.TuiLayout.KANBAN`): tasks are bucketed into one
    column per configured status (``ctx.config.statuses``), plus an extra
    ``(other)`` column for any task whose status is not in the configured
    list so an unexpected status never silently disappears.

    The cursor tracks a ``(column, row)`` position so ``j``/``k`` move within
    the focused column and ``h``/``l`` (and the left/right arrows) *navigate
    the selection* across adjacent columns (swim lanes) without changing any
    task. Moving a *card* between columns (a status change routed through
    :mod:`doxtr_doto.cli.tui.actions`) is bound to ``Tab``/``Shift+Tab`` at the
    app level (:meth:`move_target_status` computes the target). (Textual
    offers no practical drag-and-drop in a terminal, so the ``Tab`` card-move
    is the keyboard equivalent of dragging a card.)

    The columns are laid out *left-to-right* (side by side), like a real
    kanban board: :meth:`format_column` renders each status column as its own
    block of lines and :meth:`format_board` zips those blocks into aligned
    board rows whose column width is computed from the available screen width
    (:meth:`column_width`) rather than a single fixed constant, so the columns
    space evenly and cards never spill into the next column.

    Each card is a small *framed, fixed-size* block drawn with box-drawing
    characters (see :meth:`format_card`): the card is constrained in **both**
    width and height so it reads as an (approximately) square tile rather than
    a variable-height block. Because a terminal character cell is about twice
    as tall as it is wide, a visual square uses roughly ``width / CARD_ASPECT``
    rows (:meth:`card_interior_rows`), so the fixed card height tracks the
    column width via :attr:`CARD_ASPECT`. The first content line carries the
    task ID and its due date (a :attr:`DUE_PLACEHOLDER` when the task has
    none), with the priority appended when the column is wide enough
    (:meth:`show_priority`); the task's title/description is wrapped underneath
    and *clipped with an ellipsis* (:meth:`clip_body`) when it does not fit the
    fixed footprint, so a long body never makes the card grow. The whole card
    is wrapped in a frame; when the card is selected its *frame* is
    highlighted (:meth:`frame_style`) instead of reverse-videoing the entire
    card. Independently of any card highlight, the *active* (focused) column's
    header and - when the lane is empty - its ``(empty)`` placeholder are
    colored with :attr:`ACTIVE_COLUMN_STYLE` (:meth:`format_header` /
    :meth:`format_empty_placeholder`) so the user always sees which lane is
    active, including a lane that holds no card and so has no highlighted card
    frame to mark it.

    Column bucketing (:meth:`bucket_by_status`), the card-move target
    status (:meth:`move_target_status`), the per-column lines
    (:meth:`format_column`) and the full-board markup (:meth:`format_board`)
    are pure, overridable classmethods so a child theme can replace rendering
    or the move semantics by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.kanban_view_class`.
    """

    #: Column key used for tasks whose status is not in the configured list.
    OTHER_COLUMN = "(other)"

    #: Placeholder shown on a card's first line in place of a due date when
    #: the task has none, so an undated card still reserves space on the first
    #: line (ID + due). This fixed-length placeholder (8 cells) differs from an
    #: ISO date (10 cells), so it does not by itself make the first line a
    #: single stable width; the live per-lane width now comes from
    #: :meth:`column_width` / the viewport, while :meth:`min_card_width` drives
    #: the priority-fit measurement and the unmounted natural width (it
    #: measures the widest first line - dated or placeholder - across the
    #: board). Overridable (a class attribute).
    DUE_PLACEHOLDER = "(no due)"

    #: Floor on a column's visible width (screen columns) regardless of the
    #: available width / column count: the live/mounted board never renders
    #: columns narrower than this floor. When a lane this narrow cannot hold a
    #: card's natural ``ID + due`` first line the ID is **middle-truncated**
    #: (:meth:`truncate_id`) to fit rather than widening the column. Only on
    #: the *unmounted* fallback path (no live viewport, e.g. pure-logic tests)
    #: is the effective minimum the larger of this and the widest
    #: ``ID + DUE_PLACEHOLDER`` first line measured per board
    #: (:meth:`min_card_width`). Overridable (a class attribute).
    MIN_COLUMN_WIDTH: int = 16

    #: Extra visible width a column must have, beyond the minimum ``ID + due``
    #: first line, before the priority badge is also shown on that first line
    #: (:meth:`show_priority`). Lets a child theme tune how eagerly priority
    #: appears. Overridable (a class attribute).
    PRIORITY_WIDTH: int = 6

    #: Fallback column width used when the view's own ``size.width`` is not yet
    #: known (e.g. pure-logic unit tests that call ``format_board`` directly
    #: or a rebuild before mount). Wide enough to show ``ID + due`` plus the
    #: priority badge. Overridable (a class attribute).
    DEFAULT_COLUMN_WIDTH: int = 26

    #: Number of header lines :meth:`format_column` emits before the first
    #: card block (the ``── name (n) ──`` title row). :meth:`cursor_line`
    #: adds this to the cumulative height of the cards above the cursor to
    #: find its content line. A child theme overriding :meth:`format_column`
    #: to change how many header lines precede the cards must keep
    #: ``HEADER_LINES`` in sync so scroll-follow still lands on the right
    #: line. Overridable (a class attribute).
    #:
    #: Framed square cards (Feature 1/2) occupy a *fixed* footprint, so unlike
    #: the former variable-height cards the count summed by :meth:`cursor_line`
    #: no longer depends on how long a card's body is - only on the fixed
    #: :meth:`card_height`. The header count itself is unchanged.
    HEADER_LINES: int = 1

    #: Separator placed between adjacent columns in a board row.
    COLUMN_GAP = "  "

    #: Separator placed between the inter-element parts of a card's first line
    #: (between the ID and the due date, and before the priority badge) in
    #: :meth:`format_card_first_line`. Hoisted into a single class attribute
    #: (mirroring how :attr:`COLUMN_GAP` backs both :meth:`column_width`'s gap
    #: math and :meth:`format_board`'s join) so the rendered separator and the
    #: ID-truncation budget math stay in lockstep and a child theme can tune
    #: the first-line spacing in one place. Overridable (a class attribute).
    FIRST_LINE_GAP: str = "  "

    #: Terminal cell aspect ratio used to make a card look (approximately)
    #: square on screen. A terminal character cell is roughly twice as tall as
    #: it is wide, so a card that is ``N`` columns wide needs only about
    #: ``N / CARD_ASPECT`` *rows* to read as a visual square rather than a tall
    #: rectangle. :meth:`card_interior_rows` divides the card's inner width by
    #: this constant to derive how many body rows a square card gets.
    #: Overridable (a class attribute) so a child theme can tune the look for
    #: fonts/terminals with a different cell aspect.
    CARD_ASPECT: float = 2.0

    #: Floor on the number of *interior* content rows a card reserves (the
    #: rows between the top and bottom frame borders), regardless of how
    #: narrow the derived square would be. Guarantees a card always shows at
    #: least its ID + due first line plus one body line even in a very narrow
    #: column. Overridable (a class attribute).
    MIN_CARD_ROWS: int = 2

    #: Ceiling on the number of interior content rows a card reserves, so a
    #: very wide column does not produce an absurdly tall card. The body text
    #: that does not fit the derived rows is clipped with an ellipsis
    #: (:meth:`clip_body`) rather than letting the card grow. Overridable (a
    #: class attribute).
    MAX_CARD_ROWS: int = 8

    #: Box-drawing characters used to draw a card's frame
    #: (:meth:`format_frame_top` / :meth:`format_frame_bottom` / the body row
    #: side borders). A child theme can swap in a different corner/edge set.
    #: Order: top-left, top-right, bottom-left, bottom-right, horizontal,
    #: vertical.
    FRAME_CHARS: tuple[str, str, str, str, str, str] = (
        "\u256d",  # top-left     ╭
        "\u256e",  # top-right    ╮
        "\u2570",  # bottom-left  ╰
        "\u256f",  # bottom-right ╯
        "\u2500",  # horizontal   ─
        "\u2502",  # vertical     │
    )

    #: Fallback Textual style applied to a *selected* card's frame (border +
    #: corners) when no live accent is published (:attr:`SELECTED_FRAME_ACCENT`
    #: is empty) - the pure-logic / no-accent default. Uses ``bold reverse``
    #: (not a hardcoded hue such as ``cyan``): ``reverse`` inverts the theme's
    #: own fg/bg pair, so the selected frame stays contrast-visible against the
    #: surface on every built-in theme - light *and* dark - mirroring
    #: :attr:`ACTIVE_COLUMN_STYLE`. A Textual CSS theme *token* like ``$accent``
    #: must never be embedded here: those resolve only in CSS, never in Rich/
    #: Textual console markup, where they would crash or be silently ignored.
    #: When a theme hue *is* wanted it is resolved to a concrete hex at render
    #: time and published onto :attr:`SELECTED_FRAME_ACCENT` (exactly like the
    #: title bracket highlight), which :meth:`frame_style` prefers.
    #: Overridable (a class attribute); :meth:`frame_style` is the pure
    #: classmethod a child theme overrides to restyle the selected frame.
    SELECTED_FRAME_STYLE: str = "bold reverse"

    #: Concrete accent hex the live TUI publishes so a *selected* card's frame
    #: is drawn in the active theme's accent colour (the hue the Textual footer
    #: uses for key labels like ``tab``, and the same accent the title bracket
    #: highlight uses). The live app sets this at mount / theme-change with the
    #: resolved accent hex (:meth:`DotoApp.refresh_accent_highlights`); it must
    #: be a markup value both Rich and Textual understand (a concrete colour
    #: like ``"#ffa62b"`` - *not* a ``$accent`` CSS token, which Rich markup
    #: cannot resolve). When set, :meth:`frame_style` prefers it over
    #: :attr:`SELECTED_FRAME_STYLE`; the empty default keeps pure-logic callers/
    #: tests and the no-accent case on the theme-safe ``bold reverse``
    #: highlight. Overridable per widget class (child-theme seam), mirroring
    #: :attr:`TitleHighlight.BRACKET_HIGHLIGHT_STYLE`.
    SELECTED_FRAME_ACCENT: str = ""

    #: Textual style applied to an *unselected* card's frame. Empty means no
    #: styling (the terminal's default foreground). Overridable.
    FRAME_STYLE: str = "dim"

    #: Indicator appended to body text that is clipped because it does not fit
    #: the card's fixed square footprint (:meth:`clip_body`). Overridable.
    CLIP_INDICATOR: str = "\u2026"  # …

    #: Ellipsis inserted into the *middle* of a task ID that is too long to fit
    #: its card's first-line budget (:meth:`truncate_id`). IDs are shortened by
    #: dropping characters out of the middle - keeping the head and tail - so a
    #: long ``ABCDEFGH-1234567`` becomes ``ABCD…4567`` rather than losing its
    #: tail to end-truncation. This is a *separate knob* from
    #: :attr:`CLIP_INDICATOR` (which marks end-clipped body text): a child
    #: theme can restyle ID shortening alone by overriding this attribute (or
    #: :meth:`truncate_id`) without touching the body-clip indicator or the
    #: layout math. Overridable (a class attribute).
    ID_ELLIPSIS: str = "\u2026"  # …

    #: Textual style applied to the *active* (focused) column's header and its
    #: ``(empty)`` placeholder so the user always sees which lane is active -
    #: even when the lane holds no card and so has no highlighted card frame to
    #: mark it. ``bold reverse`` emphasis, consistent with the ``bold`` headers
    #: and the :attr:`SELECTED_FRAME_STYLE` *fallback* highlight (the selected
    #: frame now normally renders in the live accent; reverse is only its
    #: no-accent fallback). The style is
    #: applied via
    #: :func:`doxtr_doto.cli.tui.theme.styled`, which wraps the text in Textual
    #: markup that occupies no screen columns, so coloring the header/
    #: placeholder does not change any computed column width (widths are
    #: measured with markup stripped). Overridable (a class attribute) so a
    #: child theme can restyle the active-column indicator in one place,
    #: mirroring :attr:`SELECTED_FRAME_STYLE` / :attr:`FRAME_STYLE`.
    #:
    #: Uses ``bold reverse`` (not a hardcoded hue such as ``bold cyan``) so the
    #: active lane header is drawn by *swapping* the theme's own foreground and
    #: background into a filled, inverted block behind the lane name.
    #: Reverse-video is the most robust cross-theme highlight for a
    #: selected/active element: it is always high-contrast because it reuses
    #: the theme's own fg/bg pair (never a single fixed hue), so the active
    #: lane name (e.g. ``Open``) is always a clearly delineated inverted block
    #: on every built-in theme - including the light themes
    #: (``textual-light``/``ansi-light``/``solarized-light``) where the old
    #: thin ``bold cyan`` text blended into the light background and was
    #: effectively invisible.
    ACTIVE_COLUMN_STYLE: str = "bold reverse"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the board with empty columns and a zeroed cursor."""
        super().__init__(*args, **kwargs)
        self.statuses: list[str] = []
        self.columns: list[tuple[str, list[dict[str, Any]]]] = []
        self.col: int = 0
        self.row: int = 0
        #: The column width used by the most recent :meth:`rebuild`, cached so
        #: :meth:`cursor_line` can reproduce the exact multi-line card heights.
        self._column_width: int = self.DEFAULT_COLUMN_WIDTH
        #: The last *live* available width (the scrollbar-aware usable
        #: content width > 0) seen while the view was mounted, cached so a
        #: rebuild that momentarily reports a width of 0 (e.g. a
        #: completion-triggered rebuild running before Textual re-lays-out the
        #: board) reuses the last good width instead of falling back to the
        #: natural wide width - which overflows the viewport and wraps the
        #: board into a 2-column grid (Feature B). 0 until the first time the
        #: mounted view reports a real width.
        self._last_live_width: int = 0
        #: Whether the most recent :meth:`rebuild` showed the priority badge,
        #: cached for the same reason as :attr:`_column_width`.
        self._show_priority: bool = False

    def _available_width(self) -> int:
        """Return the usable content width excluding the vertical scrollbar.

        The board lays every status column out side by side, so the row width
        is ``count * col_width + gaps`` and must fit the *usable* content area.
        When the view (a :class:`~textual.containers.VerticalScroll`) shows a
        vertical scrollbar, that scrollbar consumes columns that ``size.width``
        still counts, so laying the board out to ``size.width`` makes the row 1
        or 2 cells too wide and Textual soft-wraps it (the rightmost column's
        frame top is pushed under the leftmost column). The scrollbar-aware
        usable width is :attr:`scrollable_content_region` ``.width`` - the
        content area *after* the vertical scrollbar is subtracted - which
        equals ``size.width`` when no scrollbar is shown, so the board row
        always fits and never wraps.

        The view knows its geometry only once mounted; before that (pure-logic
        tests, or a rebuild before :meth:`compose`) there is none. When mounted
        the live scrollbar-aware width is cached in :attr:`_last_live_width`
        whenever it is positive, and a mounted view that momentarily reports 0
        (e.g. a completion-triggered rebuild that runs before Textual
        re-lays-out the board) reuses that last good width instead of returning
        0 - which would make :meth:`column_width` fall back to the natural wide
        width and wrap the board into a 2-column grid (Feature B). Only a
        never-mounted view (no live width ever seen) still returns 0 so
        pure-logic callers get the deterministic :attr:`DEFAULT_COLUMN_WIDTH`
        path.

        Returns:
            The usable content width (scrollbar excluded): the live
            scrollbar-aware width when positive, else the last cached live
            width, else 0 when never mounted.
        """
        if not self.is_mounted:
            return self._last_live_width
        live = self.scrollable_content_region.width
        if live > 0:
            self._last_live_width = live
            return live
        return self._last_live_width

    def rebuild(self, tasks: list[dict[str, Any]], statuses: list[str] | None = None) -> None:
        """Rebuild the board from task dicts and the configured statuses.

        The cursor is preserved by task id where possible so a status move
        keeps the moved card highlighted in its new column.

        ``statuses`` is view-specific (kanban columns come from
        ``ctx.config.statuses``), so it widens the shared
        :meth:`AltLayoutView.rebuild` contract with an optional second
        argument. The app always passes it via the ``ALT_LAYOUTS`` rebuild
        adapter; when omitted the previously configured columns are reused.

        The column width (and whether the priority badge fits) is computed
        from the view's available width and the number of columns
        (:meth:`column_width` / :meth:`show_priority`) and cached so
        :meth:`cursor_line` can reproduce the per-card line heights.

        Args:
            tasks: Task dicts to place on the board.
            statuses: The configured status columns (``ctx.config.statuses``).
                Defaults to the columns from the previous rebuild when None.
        """
        resolved = self.statuses if statuses is None else statuses
        previous = self.selected_id()
        self.statuses = list(resolved)
        self.columns = self.bucket_by_status(tasks, resolved)
        self._restore_cursor(previous)
        self._render_board()

    def _render_board(self) -> None:
        """Recompute the column geometry and re-render the board markup.

        Split out of :meth:`rebuild` so the board can be re-rendered from the
        already-bucketed :attr:`columns` *without* re-bucketing tasks - in
        particular on a resize (:meth:`on_resize`), where only the available
        width changed. The per-column width (and whether the priority badge
        fits) is recomputed from the view's current :meth:`_available_width`
        and cached (:attr:`_column_width` / :attr:`_show_priority`) so
        :meth:`cursor_line` can reproduce the per-card line heights, then the
        board markup is written via :meth:`update_content`.
        """
        self._column_width = self.column_width(self.columns, self._available_width())
        self._show_priority = self.show_priority(self.columns, self._column_width)
        self.update_content(
            self.format_board(
                self.columns,
                self.col,
                self.row,
                width=self._column_width,
                show_priority=self._show_priority,
            )
        )
        self._sync_scroll_anchor()
        self.scroll_to_cursor()

    def on_resize(self, event: Any) -> None:
        """Re-render the board when the view's geometry changes.

        The board lays every status column out *side by side*, so the
        per-column width (:meth:`column_width`) depends on the view's live
        scrollbar-aware usable width (:meth:`_available_width`). At first mount
        Textual has not completed its initial layout pass when
        :meth:`DotoApp.on_mount` calls :meth:`rebuild`, so the live width is
        still 0; the first real :class:`~textual.events.Resize` posted once the
        size is known re-renders here from the cached :attr:`columns` at the
        correct width, with no card re-bucketing. That same resize is also what
        first populates :attr:`_last_live_width` (via :meth:`_available_width`),
        so a *later* rebuild that momentarily reports a width of 0 - e.g. a
        completion-triggered rebuild (``d``) that runs before Textual
        re-lays-out the board - reuses the cached live width instead of
        wrapping into a 2-column grid (Feature B).

        A vertical scrollbar appearing or disappearing changes the usable
        content width (:attr:`scrollable_content_region` ``.width``) *without*
        changing the view's outer region size, so Textual does **not** post a
        :class:`~textual.events.Resize` for a pure scrollbar toggle (the
        compositor only resizes widgets whose region size changed). A mid-
        session toggle (a lane growing past the scroll threshold) is handled
        instead by :meth:`watch_show_vertical_scrollbar`, which re-renders the
        board at the new scrollbar-aware width. A no-op before the first
        :meth:`rebuild` (no columns yet).

        Args:
            event: The Textual :class:`~textual.events.Resize` event (unused;
                the new width is read from :meth:`_available_width`).
        """
        if self.columns:
            self._render_board()

    def watch_show_vertical_scrollbar(self, show: bool) -> None:
        """Re-render the board when the vertical scrollbar toggles.

        A vertical scrollbar is drawn *inside* the view's own region, so a
        pure scrollbar toggle (a lane growing or shrinking across the scroll
        threshold mid-session) narrows or widens the usable content width
        (:attr:`scrollable_content_region` ``.width``) without changing the
        view's outer region size - and Textual therefore posts no
        :class:`~textual.events.Resize`, so :meth:`on_resize` does not fire.
        Without this hook the board would stay rendered at the pre-toggle
        width, re-introducing the exact 1-cell overflow the scrollbar-aware
        :meth:`_available_width` fix targets. ``show_vertical_scrollbar`` is a
        layout reactive, so this watcher runs on every toggle; it re-renders
        from the cached :attr:`columns` at the new width with no card
        re-bucketing. A no-op before the first :meth:`rebuild` (no columns
        yet).

        Args:
            show: Whether the vertical scrollbar is now shown (unused; the new
                width is read from :meth:`_available_width`).
        """
        if self.columns:
            self._render_board()

    def _restore_cursor(self, task_id: str | None) -> None:
        """Place the cursor on ``task_id`` when still present, else clamp it.

        Args:
            task_id: The previously highlighted task id, or None.
        """
        if task_id is not None:
            for col_index, (_name, items) in enumerate(self.columns):
                for row_index, task in enumerate(items):
                    if task.get("id") == task_id:
                        self.col = col_index
                        self.row = row_index
                        return
        self.col = max(0, min(len(self.columns) - 1, self.col))
        self.row = max(0, min(self._column_len(self.col) - 1, self.row))

    def _column_len(self, col: int) -> int:
        """Return the number of cards in column ``col`` (0 when out of range)."""
        if 0 <= col < len(self.columns):
            return len(self.columns[col][1])
        return 0

    def selected_id(self) -> str | None:
        """Return the id of the currently highlighted card.

        Returns:
            The highlighted card's task id, or None when the board is empty.
        """
        if 0 <= self.col < len(self.columns):
            items = self.columns[self.col][1]
            if 0 <= self.row < len(items):
                return str(items[self.row].get("id", ""))
        return None

    def move_cursor(self, delta: int) -> None:
        """Move the highlighted card up/down within the focused column.

        Args:
            delta: Rows to move (negative moves up).
        """
        length = self._column_len(self.col)
        if length == 0:
            return
        self.row = max(0, min(length - 1, self.row + delta))
        self.scroll_to_cursor()

    def move_cursor_to_edge(self, to_bottom: bool) -> None:
        """Jump the selection to the first / last card of the *current lane*.

        The jump-to-edge counterpart of :meth:`move_cursor`: it snaps
        :attr:`row` to ``0`` (first card) or the last card *within the focused
        column* (:attr:`col`), leaving :attr:`col` untouched - so Shift+Up /
        Shift+Down move the selection cursor inside the current swim lane and
        never move a card between lanes (that is ``Tab`` / ``Shift+Tab``). It
        is relative to whichever lane is current, so switching lanes with
        ``h``/``l`` and jumping again lands on the first / last card of the
        now-current lane. The frame then scrolls straight to the matching
        content edge (:meth:`~AltLayoutView.scroll_cursor_to_edge`) because the
        jump is discontinuous and its direction is known. A no-op on an empty
        column.

        Args:
            to_bottom: Jump to the last card when True, the first when False.
        """
        length = self._column_len(self.col)
        if length == 0:
            return
        self.row = length - 1 if to_bottom else 0
        self.scroll_cursor_to_edge(to_bottom)

    def select_id(self, task_id: str) -> bool:
        """Place the cursor on the card whose id equals ``task_id``.

        Scans the bucketed :attr:`columns` for a card with that display id and,
        when found, sets :attr:`col` / :attr:`row` to it (mirrors the
        find-by-id scan in :meth:`_restore_cursor`) and repositions it into
        view via the discontinuous :meth:`~AltLayoutView.ensure_cursor_visible`
        path (selecting by id can jump across lanes, so direction-inferring
        :meth:`~AltLayoutView.scroll_to_cursor` could leave it off screen). See
        :meth:`AltLayoutView.select_id` for the overall contract.

        Args:
            task_id: The display id (bare or namespaced) to select.

        Returns:
            True when a card with ``task_id`` was found and selected, False
            otherwise.
        """
        for col_index, (_name, items) in enumerate(self.columns):
            for row_index, task in enumerate(items):
                if str(task.get("id", "")) == task_id:
                    self.col = col_index
                    self.row = row_index
                    self.ensure_cursor_visible()
                    return True
        return False

    def move_column(self, delta: int) -> bool:
        """Move the *selection* to the next/previous column (swim lane).

        Unlike :meth:`move_target_status` - which *moves a card* to another
        column (a status change, bound to the app's ``Tab``/``Shift+Tab``) -
        this only relocates the cursor across the columns so the user can
        select a card in a different lane without changing any task; it is the
        left/right arrow and ``h``/``l`` navigation. The row is clamped into
        the destination column's range (snapping to its last card when the
        destination is shorter, or leaving the cursor at row 0 for an empty
        column) so the selection always lands on a valid card where one
        exists.

        Returns False when the move would step off either edge of the board
        (no wrap), so the caller can treat an edge as a no-op.

        A lane switch is a *discontinuous* jump (the new lane can be much
        shorter than the old one, and the clamped row can land anywhere), so
        the selected card must be repositioned into view via
        :meth:`~AltLayoutView.ensure_cursor_visible` rather than the
        direction-inferring :meth:`~AltLayoutView.scroll_to_cursor`: switching
        from the bottom of a long lane to a one-card lane whose card is at the
        top must scroll the viewport back to the top so the selected card is
        visible, which the stale smart-scroll direction baseline would not do.
        That reposition is owned by the app's :meth:`DotoApp._kanban_navigate`
        *after* it rebuilds the board (the rebuild re-renders and re-runs the
        direction-inferring smart scroll, so repositioning here would be
        overwritten); this method keeps itself on the continuous
        :meth:`~AltLayoutView.scroll_to_cursor` path for any future direct
        caller that is not followed by a rebuild.

        Args:
            delta: Columns to move (``-1`` left, ``+1`` right).

        Returns:
            True when the cursor moved to another column, False at the edges.
        """
        target = self.col + delta
        if target < 0 or target >= len(self.columns):
            return False
        self.col = target
        length = self._column_len(self.col)
        self.row = max(0, min(length - 1, self.row)) if length else 0
        self.scroll_to_cursor()
        return True

    def cursor_line(self) -> int:
        """Return the content line of the highlighted card.

        With columns laid out side by side, every card *block* shares a run of
        content lines across all columns; because cards are multi-line
        (:meth:`format_card`), the highlighted card's first line is the
        column header line(s) (:attr:`HEADER_LINES`) plus the cumulative
        height of every card above it in the focused column. The per-card
        heights are reproduced with the column width / priority flag the most
        recent :meth:`rebuild` cached (:attr:`_column_width` /
        :attr:`_show_priority`) so scroll-follow lands on the right line even
        when earlier cards wrapped to several lines.

        Returns:
            The highlighted card's 0-based first content line.
        """
        line = self.HEADER_LINES
        items = self.columns[self.col][1] if 0 <= self.col < len(self.columns) else []
        for row_index in range(min(self.row, len(items))):
            line += self.card_height(
                items[row_index],
                width=self._column_width,
                show_priority=self._show_priority,
            )
        return line

    def cursor_span(self) -> int:
        """Return the highlighted card's full height in content lines.

        Each card is a fixed, multi-line block (:meth:`format_card`), so the
        shared smart-scroll algorithm (:meth:`AltLayoutView.target_scroll_y`)
        must know the card's whole line span to keep the *entire* selected
        card on screen rather than only its top line. Reuses the same column
        width / priority flag the most recent :meth:`rebuild` cached
        (:attr:`_column_width` / :attr:`_show_priority`) so the span matches
        the rendered card height exactly - :meth:`card_height` already encodes
        ``2 + card_interior_rows(width)``. When the cursor is out of range (no
        valid card) it falls back to the base single-line span rather than
        fabricating a card height, mirroring :meth:`cursor_line`'s defensive
        bounds handling.

        Returns:
            The highlighted card's fixed line span (its :meth:`card_height`).
        """
        items = self.columns[self.col][1] if 0 <= self.col < len(self.columns) else []
        if not 0 <= self.row < len(items):
            return super().cursor_span()
        return self.card_height(
            items[self.row],
            width=self._column_width,
            show_priority=self._show_priority,
        )

    def move_target_status(self, delta: int) -> str | None:
        """Return the status to move the selected card to (``Tab`` card-move).

        Computes the status of the column ``delta`` columns away from the
        selected card's current column, which the app writes via
        :func:`doxtr_doto.cli.tui.actions.update_task` when ``Tab`` (forward)
        or ``Shift+Tab`` (back) is pressed. Only configured-status columns are
        valid targets, so a move into the ``(other)`` column (or off either
        edge) returns None (no-op). This is the terminal equivalent of
        dragging a card to the neighboring column.

        Args:
            delta: Direction/distance to move (``-1`` left, ``+1`` right).

        Returns:
            The target status string, or None when the move is not possible.
        """
        if self.selected_id() is None:
            return None
        target_col = self.col + delta
        if target_col < 0 or target_col >= len(self.columns):
            return None
        name = self.columns[target_col][0]
        if name == self.OTHER_COLUMN or name not in self.statuses:
            return None
        return name

    @classmethod
    def bucket_by_status(
        cls,
        tasks: list[dict[str, Any]],
        statuses: list[str],
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        """Group tasks into one list per status column.

        Each configured status becomes a column (in configured order); any
        task whose status is not among the configured statuses is collected
        into a trailing :attr:`OTHER_COLUMN` column, which is only included
        when it is non-empty. This keeps a task with an unexpected status
        visible rather than dropping it. Within each column the active
        (time-recorded) task is pinned to the top of its lane via
        :func:`pin_active_first` (Feature A), stable otherwise.

        Args:
            tasks: The task dicts to bucket.
            statuses: The configured status columns.

        Returns:
            An ordered list of ``(column_name, tasks)`` pairs.
        """
        buckets: dict[str, list[dict[str, Any]]] = {status: [] for status in statuses}
        other: list[dict[str, Any]] = []
        for task in tasks:
            status = task.get("status") or ""
            if status in buckets:
                buckets[status].append(task)
            else:
                other.append(task)
        columns: list[tuple[str, list[dict[str, Any]]]] = [
            (status, pin_active_first(buckets[status])) for status in statuses
        ]
        if other:
            columns.append((cls.OTHER_COLUMN, pin_active_first(other)))
        return columns

    @classmethod
    def frame_overhead(cls) -> int:
        """Return the horizontal cells a card's frame consumes per row.

        Each framed body row is ``vertical border + content + vertical
        border``, so the frame costs two visible columns of the per-column
        width (Feature 2). Kept as a named classmethod so a child theme that
        changes :attr:`FRAME_CHARS` to a wider border can adjust the width math
        in one place, and so :meth:`min_card_width` / :meth:`format_card` /
        :meth:`wrap_text` agree on the inner content width.

        Returns:
            The number of visible columns the frame borders occupy on a row.
        """
        return 2

    @classmethod
    def min_card_width(cls, columns: list[tuple[str, list[dict[str, Any]]]]) -> int:
        """Return the minimum column width needed for every card's ID + due line.

        The required minimum is driven by the widest ``ID + due`` first line
        across all cards on the board - using :attr:`DUE_PLACEHOLDER` for the
        length when a task has no due date so the width is stable - plus the
        card :meth:`frame_overhead` (the box-drawing side borders), clamped up
        to :attr:`MIN_COLUMN_WIDTH`. Measured against the visible first-line
        layout (:meth:`format_card_first_line`) so the computed width exactly
        fits the content a framed card must show. Column headers are included
        so a column title never clips either (headers are unframed, so they do
        not add the frame overhead).

        Args:
            columns: The ``(column_name, tasks)`` pairs from
                :meth:`bucket_by_status`.

        Returns:
            The minimum column width in visible screen columns.
        """
        widest = cls.MIN_COLUMN_WIDTH
        overhead = cls.frame_overhead()
        for name, items in columns:
            header = _Text.from_markup(cls.format_header(name, len(items))).cell_len
            widest = max(widest, header)
            for task in items:
                first = cls.format_card_first_line(task, show_priority=False)
                widest = max(widest, _Text.from_markup(first).cell_len + overhead)
        return widest

    @classmethod
    def column_width(
        cls,
        columns: list[tuple[str, list[dict[str, Any]]]],
        available: int,
    ) -> int:
        """Return the per-column visible width for the current board.

        The board must render **every** configured status column *side by
        side* and never wrap into a grid, so the width is derived from the
        ``available`` screen width **first**: the columns split the available
        width evenly (less the inter-column gaps) so the whole board row
        (``count * width + gaps``) fits the viewport. The result is floored at
        :attr:`MIN_COLUMN_WIDTH` (the absolute minimum a card's frame + a
        middle-truncated ID can occupy) rather than clamped *up* to
        :meth:`min_card_width`: forcing the column as wide as the widest
        natural ``ID + due`` line is exactly what used to push
        ``count * width + gaps`` past the viewport and wrap the board into a
        2x2 grid. When a column cannot hold a card's natural ID at this width
        the ID is middle-truncated to fit (:meth:`truncate_id`) instead of
        widening the column.

        When ``available`` is large enough the even split naturally exceeds
        :meth:`min_card_width`, so wide terminals still show full IDs; the
        floor only bites on constrained terminals. When ``available`` is 0 (the
        view is not yet mounted, e.g. pure-logic tests) :meth:`min_card_width`
        (clamped up to :attr:`DEFAULT_COLUMN_WIDTH`) is used so rendering stays
        deterministic and shows full IDs without a live viewport.

        Args:
            columns: The ``(column_name, tasks)`` pairs from
                :meth:`bucket_by_status`.
            available: The view's available inner width (0 when unmounted).

        Returns:
            The per-column width in visible screen columns. The total board row
            width (``count * width + gaps``) fits ``available`` whenever
            ``available >= count * MIN_COLUMN_WIDTH + gaps``.
        """
        count = len(columns)
        if available <= 0 or count == 0:
            # No live viewport: fall back to the natural width so pure-logic
            # callers / pre-mount rebuilds still show full IDs deterministically.
            return max(cls.min_card_width(columns), cls.DEFAULT_COLUMN_WIDTH)
        gaps = len(cls.COLUMN_GAP) * max(0, count - 1)
        even = (available - gaps) // count
        # Floor at the absolute minimum column width (NOT min_card_width): the
        # even split keeps the board row within the viewport, and over-long IDs
        # are middle-truncated to fit rather than widening the column.
        return max(cls.MIN_COLUMN_WIDTH, even)

    @classmethod
    def show_priority(
        cls,
        columns: list[tuple[str, list[dict[str, Any]]]],
        width: int,
    ) -> bool:
        """Return whether the priority badge fits on cards' first lines.

        Priority is shown only when the column is wider than the board's
        minimum ``ID + due`` width by at least :attr:`PRIORITY_WIDTH`, so it
        appears when there is horizontal room and is dropped when columns are
        squeezed (keeping ``ID + due`` legible).

        Args:
            columns: The ``(column_name, tasks)`` pairs from
                :meth:`bucket_by_status`.
            width: The resolved per-column width (:meth:`column_width`).

        Returns:
            True when the priority badge should be shown.
        """
        return cls._priority_fits(width, cls.min_card_width(columns))

    @classmethod
    def _priority_fits(cls, width: int, minimum: int) -> bool:
        """Return whether the priority badge fits in a column of ``width``.

        The single source of truth for the priority-fit rule: the badge is
        shown only when the column is wider than ``minimum`` (the required
        ``ID + due`` width) by at least :attr:`PRIORITY_WIDTH`. Both
        :meth:`show_priority` (which measures the board's
        :meth:`min_card_width` as the minimum) and :meth:`format_card`'s
        ``show_priority is None`` fallback (which uses the static
        :attr:`MIN_COLUMN_WIDTH` when no board is available to measure) route
        through here so the two never diverge.

        Args:
            width: The resolved per-column visible width.
            minimum: The required ``ID + due`` width the badge must clear by
                :attr:`PRIORITY_WIDTH` before it is shown.

        Returns:
            True when the priority badge should be shown.
        """
        return width >= minimum + cls.PRIORITY_WIDTH

    @classmethod
    def card_interior_rows(cls, width: int) -> int:
        """Return how many *interior* content rows a square card of ``width`` gets.

        A card is constrained in both dimensions so it reads as an
        (approximately) square tile. Because a terminal character cell is about
        twice as tall as it is wide (:attr:`CARD_ASPECT`), a card that is
        ``width`` columns wide needs only about ``width / CARD_ASPECT`` *rows*
        to look square. The result is the number of rows *between* the top and
        bottom frame borders (the ID + due first line plus the clipped body
        rows), clamped to :attr:`MIN_CARD_ROWS` / :attr:`MAX_CARD_ROWS` so the
        card never collapses below its first line + one body row nor grows
        unbounded on a very wide board.

        Args:
            width: The card's visible width (the per-column width).

        Returns:
            The number of interior content rows (>= :attr:`MIN_CARD_ROWS`).
        """
        rows = int(round(width / cls.CARD_ASPECT))
        return max(cls.MIN_CARD_ROWS, min(cls.MAX_CARD_ROWS, rows))

    @classmethod
    def card_height(
        cls,
        task: dict[str, Any],
        width: int,
        show_priority: bool,
    ) -> int:
        """Return how many content lines a card's :meth:`format_card` block spans.

        The single named place the per-card height is computed. With the
        framed, fixed-size square cards (Feature 1) every card occupies the
        **same** footprint regardless of its body length: the top frame border
        (1 row), :meth:`card_interior_rows` interior content rows, and the
        bottom frame border (1 row). This counts those rows *without* building
        any markup, so :meth:`cursor_line` can sum card heights on every
        keypress without re-rendering cards. :meth:`format_card` produces
        exactly this many lines, so the two stay in lockstep.

        Args:
            task: A task dict (unused now that height is fixed, kept for
                signature symmetry with :meth:`format_card` and so a child
                theme can make height task-dependent again by overriding).
            width: The column's visible width used to derive the square's row
                count (:meth:`card_interior_rows`).
            show_priority: Whether the first line carries the priority badge
                (does not change the height, kept for signature symmetry with
                :meth:`format_card`).

        Returns:
            The fixed number of content lines the card occupies (frame top +
            interior rows + frame bottom).
        """
        return 2 + cls.card_interior_rows(width)

    @classmethod
    def _cell_width(cls, text: str) -> int:
        """Return the visible (screen-column) width of plain ``text``.

        Measured via :class:`rich.text.Text` so wide characters (CJK, emoji)
        and zero-width characters are counted by the columns they occupy, not
        by code-point count - keeping body wrapping/clipping consistent with
        :meth:`pad_cell`, which also measures visible width.

        Args:
            text: The plain text to measure.

        Returns:
            The number of screen columns ``text`` occupies.
        """
        return _Text(text).cell_len

    @classmethod
    def _cell_slice(cls, text: str, width: int) -> str:
        """Return the longest prefix of ``text`` fitting ``width`` columns.

        Accumulates characters until adding the next one would exceed ``width``
        *visible* columns, so a wide character is never split across the
        boundary. Used to hard-split an over-long word and to trim a kept body
        line so the clip ellipsis survives padding.

        Args:
            text: The plain text to slice.
            width: The maximum visible width of the returned prefix.

        Returns:
            The longest prefix of ``text`` with visible width ``<= width``.
        """
        if width <= 0:
            return ""
        taken = ""
        used = 0
        for ch in text:
            step = _Text(ch).cell_len
            if used + step > width:
                break
            taken += ch
            used += step
        return taken

    @classmethod
    def _cell_slice_tail(cls, text: str, width: int) -> str:
        """Return the longest *suffix* of ``text`` fitting ``width`` columns.

        The tail-anchored mirror of :meth:`_cell_slice`: accumulates
        characters from the *end* of ``text`` until prepending the next one
        would exceed ``width`` *visible* columns, so a wide character is never
        split across the boundary. Used by :meth:`truncate_id` to keep the tail
        of a middle-truncated ID.

        Args:
            text: The plain text to slice.
            width: The maximum visible width of the returned suffix.

        Returns:
            The longest suffix of ``text`` with visible width ``<= width``.
        """
        if width <= 0:
            return ""
        taken = ""
        used = 0
        for ch in reversed(text):
            step = _Text(ch).cell_len
            if used + step > width:
                break
            taken = ch + taken
            used += step
        return taken

    @classmethod
    def truncate_id(cls, task_id: str, max_width: int) -> str:
        """Return ``task_id`` shortened to ``max_width`` by cutting its *middle*.

        IDs are shortened by dropping characters out of the **middle** of the
        string - keeping the head and the tail - and inserting a single
        :attr:`ID_ELLIPSIS` where the removed middle was. For example
        ``ABCDEFGH-1234567`` shortened to width 9 becomes ``ABCD…4567``. This
        is deliberately *not* end-truncation: the tail of an ID (often a
        disambiguating sequence number or hash suffix) is as significant as the
        head, so the body-text end-clip behavior (:meth:`clip_body` /
        :attr:`CLIP_INDICATOR`) is wrong for IDs. The returned string's visible
        width (measured via :class:`rich.text.Text`, so wide characters count
        by the columns they occupy) never exceeds ``max_width``.

        This is the single, pure, overridable place ID shortening is decided,
        kept separate from the layout math so a child theme can restyle ID
        truncation alone - by overriding this classmethod or the
        :attr:`ID_ELLIPSIS` knob - without touching :meth:`column_width`,
        :meth:`min_card_width`, or :meth:`format_card_first_line`.

        Args:
            task_id: The task ID to shorten.
            max_width: The maximum visible width the result may occupy. A
                non-positive budget returns an empty string.

        Returns:
            ``task_id`` unchanged when it already fits ``max_width``; otherwise
            a head + :attr:`ID_ELLIPSIS` + tail middle-truncation that fits.
        """
        if max_width <= 0:
            return ""
        if cls._cell_width(task_id) <= max_width:
            return task_id
        ellipsis = cls.ID_ELLIPSIS
        ellipsis_w = cls._cell_width(ellipsis)
        # No room for even head + ellipsis + tail: keep a leading prefix of the
        # TASK ID itself (its head chars) rather than wasting the whole budget
        # on a lone ellipsis, so a tiny budget still shows real ID characters.
        if max_width <= ellipsis_w:
            return cls._cell_slice(task_id, max_width)
        content = max_width - ellipsis_w
        # Split the surviving width between head and tail, favoring the head by
        # one column on an odd budget so a short ID keeps a readable prefix.
        head_budget = content - content // 2
        tail_budget = content // 2
        head = cls._cell_slice(task_id, head_budget)
        tail = cls._cell_slice_tail(task_id, tail_budget)
        return f"{head}{ellipsis}{tail}"

    @classmethod
    def clip_body(
        cls, lines: list[str], max_rows: int, inner_width: int | None = None
    ) -> list[str]:
        """Clip wrapped body ``lines`` to ``max_rows``, marking the overflow.

        Keeps the framed card a fixed height: body text that does not fit the
        square footprint is truncated to ``max_rows`` lines and the last kept
        line gets a :attr:`CLIP_INDICATOR` ellipsis appended so the user can
        tell the body continues (rather than silently dropping text or letting
        the card grow). Shorter bodies are returned unchanged. ``max_rows`` of
        0 or less returns an empty list.

        When ``inner_width`` is given, the last kept line is first trimmed (by
        *visible* width) to leave room for the indicator, so the ellipsis is
        not later truncated away by :meth:`pad_cell` when the line already
        fills the inner width. ``inner_width`` is optional so existing
        pure-logic callers keep working; :meth:`format_card` always passes it.

        Args:
            lines: The wrapped body lines (:meth:`wrap_text`).
            max_rows: The number of body rows the card can show.
            inner_width: The card's inner (visible) width the lines are padded
                to; when provided, the ellipsis is guaranteed to fit.

        Returns:
            The body lines clipped to at most ``max_rows`` lines.
        """
        if max_rows <= 0:
            return []
        if len(lines) <= max_rows:
            return list(lines)
        kept = list(lines[:max_rows])
        last = kept[-1].rstrip()
        indicator = cls.CLIP_INDICATOR
        if inner_width is not None:
            # Reserve room for the ellipsis so pad_cell does not truncate it
            # back off a full-width line.
            budget = inner_width - cls._cell_width(indicator)
            if cls._cell_width(last) > budget:
                last = cls._cell_slice(last, budget)
        kept[-1] = (last + indicator) if last else indicator
        return kept

    @classmethod
    def format_board(
        cls,
        columns: list[tuple[str, list[dict[str, Any]]]],
        cursor_col: int,
        cursor_row: int,
        width: int | None = None,
        show_priority: bool | None = None,
    ) -> str:
        """Return the kanban board markup with columns laid out left-to-right.

        Each status column is rendered as its own block of lines (via
        :meth:`format_column`) and the blocks are placed *side by side*: line
        ``n`` of every column is concatenated into one board row, padded (and
        truncated) to the per-column ``width`` so the columns align into a
        board grid and no card bleeds into its neighbor. Padding/truncation is
        measured against the *visible* width of each cell (ignoring Textual
        markup) so color/reverse tags do not throw off the alignment.

        ``width`` and ``show_priority`` keep the classmethod pure: the view
        computes them from its live geometry (:meth:`column_width` /
        :meth:`show_priority`) and passes them in via :meth:`rebuild`. When
        omitted (pure-logic callers / unit tests) they are derived from the
        board itself so the method still renders a sensible, deterministic
        board without a live viewport.

        Args:
            columns: The ``(column_name, tasks)`` pairs from
                :meth:`bucket_by_status`.
            cursor_col: The focused column index.
            cursor_row: The highlighted row within the focused column.
            width: The per-column visible width; derived from the board when
                None.
            show_priority: Whether to show the priority badge; derived from the
                board/``width`` when None.

        Returns:
            Textual markup for the whole board (an empty-state line when there
            are no columns).
        """
        if not columns:
            return "[dim]No statuses configured.[/dim]"
        if width is None:
            width = cls.column_width(columns, 0)
        if show_priority is None:
            show_priority = cls.show_priority(columns, width)
        blocks = [
            cls.format_column(
                name,
                items,
                col_index == cursor_col,
                cursor_row,
                width=width,
                show_priority=show_priority,
            )
            for col_index, (name, items) in enumerate(columns)
        ]
        height = max(len(block) for block in blocks)
        rows: list[str] = []
        for line_index in range(height):
            cells: list[str] = []
            for block in blocks:
                cell = block[line_index] if line_index < len(block) else ""
                cells.append(cls.pad_cell(cell, width))
            rows.append(cls.COLUMN_GAP.join(cells).rstrip())
        return "\n".join(rows)

    @classmethod
    def format_header(cls, name: str, count: int, focused: bool = False) -> str:
        """Return a column's header line markup (``── name (n) ──``).

        Split out from :meth:`format_column` so :meth:`min_card_width` can
        measure a header's visible width without re-deriving its layout, and
        so a child theme can restyle the header alone. Keep :attr:`HEADER_LINES`
        in sync when overriding this to emit a different number of lines.

        When ``focused`` the whole header is additionally wrapped in
        :attr:`ACTIVE_COLUMN_STYLE` so the active (focused) lane is visibly
        emphasized even when the lane is empty and has no highlighted card frame
        to mark it (Feature 2). The highlight markup occupies no screen columns,
        so a focused header has the same *visible* width as an unfocused one -
        width-measuring callers (:meth:`min_card_width`, :meth:`format_board`'s
        :meth:`pad_cell`) strip markup via :class:`rich.text.Text`, so
        coloring never shifts column alignment. ``focused`` defaults to False
        so existing callers and child themes keep working unchanged.

        Args:
            name: The column (status) name.
            count: The number of cards in the column.
            focused: Whether this column currently has the cursor; when True
                the header is colored with :attr:`ACTIVE_COLUMN_STYLE`.

        Returns:
            Textual markup for the header line.
        """
        header = styled(f"── {name} ({count}) ──", "bold")
        if focused:
            return styled(header, cls.ACTIVE_COLUMN_STYLE)
        return header

    @classmethod
    def format_empty_placeholder(cls, focused: bool = False) -> str:
        """Return a column's ``(empty)`` placeholder markup.

        A column with no cards shows this placeholder in place of a card
        block. When ``focused`` the placeholder is colored with
        :attr:`ACTIVE_COLUMN_STYLE` so the active lane is still visibly marked
        even though it has no card frame to highlight (Feature 2); otherwise it
        keeps the dim styling used for an inactive empty lane. Factored out of
        :meth:`format_column` so a child theme can restyle the active/inactive
        placeholder in one place, mirroring :meth:`format_header`.

        Args:
            focused: Whether the column currently has the cursor.

        Returns:
            Textual markup for the ``(empty)`` placeholder line.
        """
        if focused:
            return styled("(empty)", cls.ACTIVE_COLUMN_STYLE)
        return "[dim](empty)[/dim]"

    @classmethod
    def format_column(
        cls,
        name: str,
        items: list[dict[str, Any]],
        focused: bool,
        cursor_row: int,
        width: int | None = None,
        show_priority: bool | None = None,
    ) -> list[str]:
        """Return one status column's lines (header + each card's block).

        Returns the column as a flat *list* of markup lines (not a joined
        string) so :meth:`format_board` can place columns side by side by
        zipping their lines. Because cards are multi-line, each card
        contributes its whole :meth:`format_card` block (first line + wrapped
        description) to the list. Overridable so a child theme can change a
        column's header/body without touching the side-by-side layout in
        :meth:`format_board`.

        When ``focused`` the column is the active lane: its header
        (:meth:`format_header`) and, when it has no cards, its ``(empty)``
        placeholder (:meth:`format_empty_placeholder`) are colored with
        :attr:`ACTIVE_COLUMN_STYLE` so the user always sees which lane is
        active - including an empty lane that has no highlighted card frame to
        mark it (Feature 2). The highlight markup occupies no screen columns, so
        it never changes the computed column width or board alignment.

        Args:
            name: The column (status) name.
            items: The tasks bucketed into this column.
            focused: Whether this column currently has the cursor.
            cursor_row: The highlighted row within the focused column (only
                applied when ``focused`` is True).
            width: The per-column visible width used to wrap card bodies;
                derived from a single-column board when None.
            show_priority: Whether to show the priority badge; derived from
                ``width`` when None.

        Returns:
            The column's markup lines: a header line, then each card's block
            (or an ``(empty)`` placeholder when the column has no cards).
        """
        if width is None:
            width = cls.column_width([(name, items)], 0)
        if show_priority is None:
            show_priority = cls.show_priority([(name, items)], width)
        lines = [cls.format_header(name, len(items), focused)]
        if not items:
            lines.append(cls.format_empty_placeholder(focused))
        for row_index, task in enumerate(items):
            highlighted = focused and row_index == cursor_row
            lines.extend(
                cls.format_card(task, highlighted, width=width, show_priority=show_priority)
            )
        return lines

    @classmethod
    def pad_cell(cls, cell: str, width: int) -> str:
        """Pad or truncate a markup ``cell`` to ``width`` *visible* columns.

        The cell may contain Textual markup (color/reverse/bold tags) that does
        not occupy screen columns, so both padding and truncation are computed
        from the cell's visible width (via :class:`rich.text.Text`) rather than
        its raw string length. A cell narrower than ``width`` is right-padded
        with spaces; a cell *wider* than ``width`` is truncated to the visible
        width (preserving markup) so a card can never spill into the next
        column.

        Args:
            cell: The markup cell to pad/truncate.
            width: The target visible column width.

        Returns:
            The cell padded or truncated to exactly ``width`` visible columns.
        """
        text = _Text.from_markup(cell)
        visible = text.cell_len
        if visible == width:
            return cell
        if visible < width:
            return cell + " " * (width - visible)
        truncated = text.copy()
        truncated.truncate(width)
        return truncated.markup

    @classmethod
    def format_card_first_line(
        cls,
        task: dict[str, Any],
        show_priority: bool,
        max_width: int | None = None,
    ) -> str:
        """Return a card's first line markup: ID + due (+ priority).

        The first line is the ID + due part of a card: the task
        ID followed by its due date (or :attr:`DUE_PLACEHOLDER` when it has
        none, a fixed-length placeholder so undated cards still reserve
        first-line space), with the priority badge
        appended when ``show_priority`` is True (the column is wide enough).
        A running task is marked with a leading indicator. The placeholder is
        not the same cell width as an ISO date, so the first-line width is not
        constant across cards; the width authority is :meth:`min_card_width`,
        which measures the widest first line on the board.

        When ``max_width`` is given, the **task ID is middle-truncated**
        (:meth:`truncate_id`) so the whole first line fits ``max_width`` visible
        columns - this is how the board keeps every status column side by side
        on a constrained terminal without widening a column past the viewport.
        The budget left for the ID is ``max_width`` minus the fixed parts of
        the line (the running indicator, the :attr:`FIRST_LINE_GAP` separators,
        the due text, and the priority badge when shown), so the due date and
        priority behavior is unchanged; only the ID is shortened, and only from
        its middle. When that budget would otherwise drop the ID entirely while
        the line still has room (e.g. a running task with a due date at the
        :attr:`MIN_COLUMN_WIDTH` floor), it is clamped up to at least the ID
        ellipsis width so the card never shows a completely blank ID; the due
        date is then clipped from the right by :meth:`pad_cell`. The
        title/description body keeps the end-clip behavior
        (:meth:`clip_body`) - IDs specifically use middle-truncation. When
        ``max_width`` is None (pure-logic callers that measure natural width,
        e.g. :meth:`min_card_width`) the ID is left intact.

        Args:
            task: A task dict.
            show_priority: Whether to append the priority badge.
            max_width: The visible-width budget the whole first line must fit;
                when given, the ID is middle-truncated to make room. None
                leaves the ID intact (natural-width measurement).

        Returns:
            Textual markup for the card's first line (no highlight wrapping).
        """
        running = "[green]\u25b6[/green] " if task.get("_running") else ""
        task_id = str(task.get("id", ""))
        due = str(task.get("due") or "") or cls.DUE_PLACEHOLDER
        pri_cell = ""
        if show_priority:
            priority = task.get("priority") or ""
            pri_cell = styled(priority[:4] or "-", priority_style(priority))
        if max_width is not None:
            # Reserve room for every fixed part of the line and middle-truncate
            # the ID into whatever budget remains, so the whole first line fits
            # ``max_width`` without widening the column.
            gap_w = cls._cell_width(cls.FIRST_LINE_GAP)
            running_w = _Text.from_markup(running).cell_len if running else 0
            due_w = cls._cell_width(due) + gap_w  # gap before the due text
            pri_w = (_Text.from_markup(pri_cell).cell_len + gap_w) if pri_cell else 0
            id_budget = max_width - running_w - due_w - pri_w
            # Floor the budget so a card never shows a completely blank ID when
            # ANY room is left: when the raw budget is below the ID ellipsis
            # width but the line still has room (after the running indicator),
            # clamp it up to at least the ellipsis width - bounded by
            # ``max_width - running_w`` so the ID + running indicator still fit
            # (the due date, which pad_cell clips from the right, yields the
            # room). If even the ellipsis cannot fit, 0 is acceptable.
            ellipsis_w = cls._cell_width(cls.ID_ELLIPSIS)
            room = max_width - running_w
            if id_budget < ellipsis_w and room > 0:
                id_budget = min(ellipsis_w, room)
            task_id = cls.truncate_id(task_id, id_budget)
        line = f"{running}[bold]{task_id}[/bold]{cls.FIRST_LINE_GAP}{due}"
        if pri_cell:
            line += f"{cls.FIRST_LINE_GAP}{pri_cell}"
        return line

    @classmethod
    def frame_style(cls, highlighted: bool) -> str:
        """Return the Textual style for a card frame (Feature 2).

        The single, pure, overridable place the frame color is decided: a
        selected card is marked by coloring its *frame* in the active theme's
        accent hex when one is published (:attr:`SELECTED_FRAME_ACCENT`),
        falling back to the theme-safe :attr:`SELECTED_FRAME_STYLE` reverse
        highlight when no accent is set, rather than reverse-videoing the whole
        card; an unselected card uses :attr:`FRAME_STYLE`. A child theme
        restyles the selected/unselected frame by overriding this classmethod
        (or the style/accent attributes) without touching the frame-drawing
        geometry in :meth:`format_card`.

        Args:
            highlighted: Whether the card is under the cursor (selected).

        Returns:
            A Textual style string (possibly empty) for the frame borders.
        """
        if highlighted:
            # Prefer the live-resolved accent hex (published by the app at
            # mount / theme-change) so the selected frame matches the theme's
            # accent, exactly like the title bracket highlight. Fall back to
            # the theme-safe ``bold reverse`` when no accent is published
            # (pure-logic callers/tests, or a theme with no accent) so the
            # highlight is never lost. ``bold #hex`` only colours the border
            # glyphs; it is width-neutral (styled() markup occupies no
            # columns), so it cannot change card width/alignment.
            if cls.SELECTED_FRAME_ACCENT:
                return f"bold {cls.SELECTED_FRAME_ACCENT}"
            return cls.SELECTED_FRAME_STYLE
        return cls.FRAME_STYLE

    @classmethod
    def format_frame_top(cls, width: int, highlighted: bool) -> str:
        """Return a card's top frame border row (``╭───╮``).

        Args:
            width: The card's visible width (the per-column width).
            highlighted: Whether the card is selected (styles the border).

        Returns:
            Textual markup for the top border row, styled via
            :meth:`frame_style`.
        """
        tl, tr, _bl, _br, horiz, _vert = cls.FRAME_CHARS
        inner = max(0, width - 2)
        return styled(f"{tl}{horiz * inner}{tr}", cls.frame_style(highlighted))

    @classmethod
    def format_frame_bottom(cls, width: int, highlighted: bool) -> str:
        """Return a card's bottom frame border row (``╰───╯``).

        Args:
            width: The card's visible width (the per-column width).
            highlighted: Whether the card is selected (styles the border).

        Returns:
            Textual markup for the bottom border row, styled via
            :meth:`frame_style`.
        """
        _tl, _tr, bl, br, horiz, _vert = cls.FRAME_CHARS
        inner = max(0, width - 2)
        return styled(f"{bl}{horiz * inner}{br}", cls.frame_style(highlighted))

    @classmethod
    def format_card_body_row(cls, content: str, width: int, highlighted: bool) -> str:
        """Return one framed interior row: ``│ content... │``.

        The side borders are styled via :meth:`frame_style` (so a selected
        card's whole frame is highlighted) while the ``content`` markup is
        placed between them, padded/truncated to the inner width so the right
        border always lines up and the card stays a fixed footprint.

        Args:
            content: The row's inner markup (first line or a body line).
            width: The card's visible width (the per-column width).
            highlighted: Whether the card is selected (styles the borders).

        Returns:
            Textual markup for one framed interior row.
        """
        *_rest, vert = cls.FRAME_CHARS
        inner = max(0, width - 2)
        border = styled(vert, cls.frame_style(highlighted))
        padded = cls.pad_cell(content, inner)
        return f"{border}{padded}{border}"

    @classmethod
    def format_card(
        cls,
        task: dict[str, Any],
        highlighted: bool,
        width: int | None = None,
        show_priority: bool | None = None,
    ) -> list[str]:
        """Return one task card's framed, fixed-size square block.

        A card is drawn as a box-framed tile constrained in both width and
        height (Feature 1) so it reads as an (approximately) square card:

        * a top frame border (:meth:`format_frame_top`),
        * :meth:`card_interior_rows` interior rows: the stable ``ID + due``
          first line (plus priority when ``show_priority``, from
          :meth:`format_card_first_line`) followed by the title/description
          wrapped to the frame's inner width (:meth:`wrap_text`) and
          **clipped with an ellipsis** (:meth:`clip_body`) when it does not fit
          - so a long body never makes the card taller - padded out with blank
          rows when the body is short so every card is the same height, and
        * a bottom frame border (:meth:`format_frame_bottom`).

        When ``highlighted`` the card's *frame* is colored (:meth:`frame_style`)
        rather than reverse-videoing the whole card (Feature 2). The number of
        lines returned is exactly :meth:`card_height`, so :meth:`format_column`
        can stack cards and :meth:`cursor_line` can sum fixed heights.

        Args:
            task: A task dict.
            highlighted: Whether this card is under the cursor (selected).
            width: The column's visible width used to size the square and wrap
                the description; derived from a single-column board when None.
            show_priority: Whether to show the priority badge; derived from
                ``width`` when None.

        Returns:
            The card's framed markup lines (exactly :meth:`card_height` lines).
        """
        if width is None:
            width = cls.DEFAULT_COLUMN_WIDTH
        if show_priority is None:
            # No board to measure, so fall back to the static minimum - routed
            # through the shared :meth:`_priority_fits` rule so this never
            # diverges from :meth:`show_priority` (which measures
            # :meth:`min_card_width`).
            show_priority = cls._priority_fits(width, cls.MIN_COLUMN_WIDTH)
        interior_rows = cls.card_interior_rows(width)
        inner = max(1, width - cls.frame_overhead())
        first = cls.format_card_first_line(task, show_priority, max_width=inner)
        # The first line consumes one interior row; the rest are body rows.
        body_rows = max(0, interior_rows - 1)
        title = str(task.get("title", ""))
        wrapped = cls.wrap_text(title, width)
        body = cls.clip_body(wrapped, body_rows, inner)
        # ``wrapped``/``body`` are plain text (wrapped/clipped by *visible*
        # width); escape each line before it is rendered as markup so a title
        # containing ``[`` / ``]`` (e.g. ``"[WIP] fix"``) renders literally and
        # keeps its true width - otherwise the brackets are parsed as a style
        # tag and the framed card misaligns (or ``"[/]"`` raises MarkupError).
        # ``escape_title`` also accent-colours each ``[...]`` run; a run split
        # across wrapped lines simply is not matched (and renders plain), which
        # is a harmless degradation for an over-long bracket token.
        body = [cls.escape_title(line) for line in body]
        # Pad the interior to exactly ``interior_rows`` so every card is the
        # same fixed height (Feature 1); blanks fill the inner width.
        contents = [first, *body]
        while len(contents) < interior_rows:
            contents.append("")
        contents = contents[:interior_rows]
        rows = [cls.format_frame_top(width, highlighted)]
        for content in contents:
            rows.append(cls.format_card_body_row(content, width, highlighted))
        rows.append(cls.format_frame_bottom(width, highlighted))
        return rows

    @classmethod
    def wrap_text(cls, text: str, width: int) -> list[str]:
        """Wrap plain ``text`` to a framed card's inner width (word-aware).

        Splits the description across as many lines as needed so no body line
        exceeds the card's inner width (the per-column width minus the frame
        :meth:`frame_overhead` side borders), preventing spill past the frame.
        A single word longer than the inner width is hard-split so it still
        never overflows. Returns an empty list for empty text (a card with no
        title is just its first line plus blank interior rows). The caller
        (:meth:`format_card`) clips the returned lines to the card's fixed row
        count (:meth:`clip_body`).

        Args:
            text: The plain description/title text to wrap.
            width: The card's visible width (the per-column width).

        Returns:
            The wrapped lines (fitting the frame's inner width).
        """
        inner = max(1, width - cls.frame_overhead())
        words = text.split()
        if not words:
            return []
        lines: list[str] = []
        current = ""
        current_w = 0
        for word in words:
            word_w = cls._cell_width(word)
            while word_w > inner:
                # Hard-split a word wider than the inner width (by visible
                # columns, so a wide character is never split).
                if current:
                    lines.append(current)
                    current = ""
                    current_w = 0
                head = cls._cell_slice(word, inner)
                lines.append(head)
                word = word[len(head) :]
                word_w = cls._cell_width(word)
            if not current:
                current = word
                current_w = word_w
            elif current_w + 1 + word_w <= inner:
                current += " " + word
                current_w += 1 + word_w
            else:
                lines.append(current)
                current = word
                current_w = word_w
        if current:
            lines.append(current)
        return lines


class CalendarView(AltLayoutView):
    """Calendar view: tasks placed on their due date in a month grid.

    This is the ``calendar`` TUI layout
    (:attr:`doxtr_doto.enums.TuiLayout.CALENDAR`): a month calendar that marks
    which days have tasks due, with a selectable day whose due tasks are
    listed below the grid. Tasks with no due date (or an unparseable one) are
    collected into a dedicated "no due date" bucket shown beneath the grid so
    the view never crashes on undated tasks.

    **Focus regions (Features A/B).** The view has three logical focus regions
    cycled with ``Tab`` (and walked in reverse with ``Shift+Tab``) through the
    app's :meth:`doxtr_doto.cli.tui.app.DotoApp.action_cycle_pane`:

    * :attr:`REGION_GRID` - the month grid (the opening region). ``h``/``l``
      (or ``left``/``right``) move the selected day by one day and ``j``/``k``
      (or ``down``/``up``) move a whole week, so day/week navigation is
      unchanged from before.
    * :attr:`REGION_DUE` - the "Due <date>" list for the selected day. A task
      is highlighted (:attr:`region_cursor`) and :meth:`selected_id` returns
      *that* task, so ``e`` (edit) / ``Enter`` / done operate on the
      highlighted due task. ``j``/``k`` move the task cursor within the list.
    * :attr:`REGION_NO_DUE` - the always-shown "No due date" list, with the
      same per-task cursor behavior; ``j``/``k`` move the cursor and
      :meth:`selected_id` returns the highlighted undated task (Feature B).

    The ``Tab`` cycle is grid -> Due -> No-due -> details pane -> grid (and
    ``Shift+Tab`` walks the exact reverse); the details-pane step is handled
    by the calendar's own ``tab_action``
    (:meth:`doxtr_doto.cli.tui.app.DotoApp._cycle_calendar_region`), which
    hands focus to / from the shared details pane (``cycles_details`` is
    ``False`` for the calendar). Moving the task cursor *past the end* of the
    Due or No-due list in the move direction advances to the adjacent region,
    so ``j``/``k`` reads intuitively as "keep moving down/up through the
    regions". ``h``/``l`` (:meth:`move_day`) always re-target the selected
    day even while a list region is focused, re-clamping the task cursor into
    the new day's list on the rebuild.

    **Assigning a due date (Feature C).** When a No-due task is highlighted and
    a calendar day is selected, pressing the app's assign-due key (``A``)
    assigns the selected day as that task's ``due`` via
    :func:`doxtr_doto.cli.tui.actions.update_task` (the task to assign is
    surfaced by :meth:`assign_task_id`), so the task leaves the no-due bucket
    and appears under that day's Due list. It is a documented no-op (with a
    notify) when no No-due task is highlighted.

    Pressing ``Enter`` on the grid reveals the selected day's first due task
    in the shared details pane; in the Due / No-due regions it reveals the
    highlighted task (see :meth:`selected_id`). The month grid stays pinned at
    the top of the viewport (:meth:`scroll_to_cursor`): because grid-region
    navigation only ever moves the selector within the grid, keeping the grid
    visible is all the keyboard needs, and the grid plus the per-day detail
    list render into a single Static so the grid cannot scroll independently
    of the detail region below it. Bucketing
    (:meth:`bucket_by_due`), the month grid (:meth:`format_calendar`) and the
    per-day detail (:meth:`format_day_detail`) are pure, overridable
    classmethods so a child theme can replace *all* rendering - including how
    the highlighted active-region task is marked - by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.calendar_view_class`. The active
    region and task cursor flow into :meth:`format_day_detail` /
    :meth:`format_entry` so the highlight markup lives entirely behind those
    overridable seams.
    """

    #: Bucket key used for tasks with no (parseable) due date.
    NO_DUE_KEY = "none"

    #: Focus-region identifiers for :attr:`focus_region`. The grid is region 0 so a
    #: freshly built view opens on day/week navigation (unchanged behavior);
    #: the "Due" list and the "No due date" list follow it in the ``Tab``
    #: cycle. The ordered :attr:`REGIONS` tuple drives :meth:`cycle_region` so
    #: adding a future list region is extending :attr:`REGIONS` plus adding one
    #: :attr:`REGION_TASK_SOURCES` entry (no cycle-logic edits).
    REGION_GRID = 0
    REGION_DUE = 1
    REGION_NO_DUE = 2

    #: The focus regions in ``Tab`` order (grid first). :meth:`cycle_region`
    #: walks this to advance / reverse the focused region. A child theme adding
    #: a region extends this tuple (and adds a :attr:`REGION_TASK_SOURCES`
    #: entry) rather than editing the cycle logic.
    REGIONS = (REGION_GRID, REGION_DUE, REGION_NO_DUE)

    #: Number of header lines :meth:`format_calendar` emits before the first
    #: week row: the ``Month Year`` title line and the ``Mo Tu ...`` weekday
    #: legend. :meth:`grid_line_count` adds this to the week-row count to
    #: measure the pinned grid region. A child theme overriding
    #: :meth:`format_calendar` to change how many header lines precede the
    #: grid must keep ``GRID_HEADER_LINES`` in sync so the pin still spans the
    #: whole grid. Overridable (a class attribute).
    GRID_HEADER_LINES: int = 2

    #: Data-driven map from a *list* focus region to a bound accessor that
    #: returns that region's backing task list, mirroring the
    #: :attr:`doxtr_doto.cli.tui.app.DotoApp.ALT_LAYOUTS` registry philosophy.
    #: :meth:`region_tasks` looks a region up here instead of branching, so
    #: adding a region is extending :attr:`REGIONS` plus adding one entry here
    #: - no edits to the cursor / clamp / selection logic. The grid region is
    #: deliberately absent (it has no per-task cursor); an absent region
    #: resolves to an empty list. Overridable (a class attribute) so a child
    #: theme can add or replace region sources.
    REGION_TASK_SOURCES: dict[int, Callable[[CalendarView], list[dict[str, Any]]]] = {
        REGION_DUE: lambda self: self.selected_tasks(),
        REGION_NO_DUE: lambda self: list(self.buckets.get(self.NO_DUE_KEY, [])),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the calendar with no tasks and no selected day."""
        super().__init__(*args, **kwargs)
        self.buckets: dict[str, list[dict[str, Any]]] = {}
        #: The selected calendar day as an ISO ``YYYY-MM-DD`` string.
        self.selected: str = ""
        #: The (year, month) the grid is showing.
        self.year: int = 0
        self.month: int = 0
        #: The focused region (one of :attr:`REGION_GRID` / :attr:`REGION_DUE`
        #: / :attr:`REGION_NO_DUE`). Starts on the grid so a freshly built view
        #: opens on day/week navigation, unchanged from before (Feature A).
        self.focus_region: int = self.REGION_GRID
        #: The task cursor within the focused Due / No-due list; unused in the
        #: grid region. Clamped into the active list on every rebuild and
        #: region change by :meth:`_clamp_region_cursor`.
        self.region_cursor: int = 0

    def rebuild(self, tasks: list[dict[str, Any]], today: _date | None = None) -> None:
        """Rebuild the calendar from task dicts.

        The selected day defaults to today on the first build and is otherwise
        preserved across rebuilds.

        Args:
            tasks: Task dicts to place on the calendar.
            today: Reference "today" (defaults to the current local date).
        """
        reference = today if today is not None else _date.today()
        self.buckets = self.bucket_by_due(tasks)
        if not self.selected:
            self.selected = reference.isoformat()
        focus = self._selected_date(reference)
        self.year, self.month = focus.year, focus.month
        self._clamp_region_cursor()
        self.update_content(
            self.format_calendar(self.buckets, self.selected, self.year, self.month)
            + "\n\n"
            + self.format_day_detail(
                self.buckets, self.selected, self.focus_region, self.region_cursor
            )
        )
        self.scroll_to_cursor()

    def _selected_date(self, reference: _date) -> _date:
        """Return the selected day as a date (falling back to ``reference``).

        Args:
            reference: The fallback date when the selection is unparseable.

        Returns:
            The parsed selected date, or ``reference`` on failure.
        """
        try:
            return _date.fromisoformat(self.selected)
        except ValueError:
            return reference

    def move_day(self, delta: int) -> None:
        """Move the selected day by ``delta`` days.

        Bound to ``h``/``l``. This always re-targets the selected day, even
        when a list region (:attr:`REGION_DUE` / :attr:`REGION_NO_DUE`) is
        focused: changing the day changes which tasks the Due list holds, so
        the next rebuild re-clamps :attr:`region_cursor` into the new day's
        list (:meth:`_clamp_region_cursor`), keeping the cursor valid.

        Args:
            delta: Number of days to move (negative moves earlier).
        """
        current = self._selected_date(_date.today())
        self.selected = (current + _timedelta(days=delta)).isoformat()

    def move_cursor(self, delta: int) -> None:
        """Move the active region's cursor by ``delta`` (``j``/``k`` navigation).

        The behavior depends on the focused :attr:`focus_region`:

        * :attr:`REGION_GRID` - move the selected day by a whole week per step
          (one grid row), so vertical navigation moves a calendar row while
          ``h``/``l`` (:meth:`move_day`) move a single day. This is the
          original grid behavior, preserved.
        * :attr:`REGION_DUE` / :attr:`REGION_NO_DUE` - move the per-task cursor
          (:attr:`region_cursor`) within the focused list. Moving past the
          list's end in the move direction *advances the focused region* (via
          :meth:`cycle_region`), so ``j``/``k`` keep flowing down/up through
          the regions. At the last region's far end (the bottom of No-due) the
          ``j`` move is a no-op; only ``Tab`` advances to the details pane.
          The grid region, in contrast, keeps moving by weeks
          rather than overflowing into a list.

        Bound to ``j``/``k`` (and the ``down``/``up`` arrows). The move stays
        within the pinned month grid for the grid region
        (:meth:`scroll_to_cursor`).

        Args:
            delta: Rows to move (negative moves up); for the grid region each
                step is a whole week.
        """
        if self.focus_region == self.REGION_GRID:
            self.move_day(delta * 7)
            return
        self._move_list_cursor(delta)

    def move_cursor_to_edge(self, to_bottom: bool) -> None:
        """Jump the active region's cursor to its first / last entry.

        Mirrors :meth:`move_cursor`'s region dispatch so Shift+Up / Shift+Down
        jump the edge of whichever region is active:

        * :attr:`REGION_GRID` - re-target the selected day to the first
          (Shift+Up) or last (Shift+Down) day of the visible month, the
          jump-to-edge analogue of the grid's week-at-a-time
          :meth:`move_day`. A no-op before the grid is populated (no
          ``year``/``month`` yet).
        * :attr:`REGION_DUE` / :attr:`REGION_NO_DUE` - snap
          :attr:`region_cursor` to the first / last row of the focused list
          (within that region, without cycling to an adjacent region), a
          no-op when the list is empty.

        Like :meth:`move_cursor`, this only relocates the cursor state; the
        app re-renders the view via
        :meth:`~doxtr_doto.cli.tui.app.DotoApp._rebuild_alt_views`
        (:meth:`rebuild`), which re-clamps the cursor and scrolls.

        Args:
            to_bottom: Jump to the last entry when True, the first when False.
        """
        if self.focus_region == self.REGION_GRID:
            if not self.year or not self.month:
                return
            last_day = _calendar.monthrange(self.year, self.month)[1]
            day = last_day if to_bottom else 1
            self.selected = _date(self.year, self.month, day).isoformat()
            return
        tasks = self.region_tasks()
        if not tasks:
            return
        self.region_cursor = len(tasks) - 1 if to_bottom else 0

    def _move_list_cursor(self, delta: int) -> None:
        """Move the task cursor within the focused Due / No-due list.

        Steps :attr:`region_cursor` by ``delta`` within the focused region's
        task list. A step that would move *before the first* row (moving up)
        or *past the last* row (moving down) advances the focused region in
        that direction via :meth:`cycle_region`, landing the cursor on the
        first row of the new region (or leaving the grid on day/week
        navigation), so ``j``/``k`` flow continuously across the regions. At
        the last region's far end (the bottom of No-due, or the grid-adjacent
        top boundary) :meth:`cycle_region` falls off the ends and returns its
        direction without moving, so the keyboard move is a silent no-op -
        only ``Tab`` hands focus to / from the details pane there.

        Args:
            delta: Rows to move (negative moves up).
        """
        tasks = self.region_tasks()
        target = self.region_cursor + delta
        if 0 <= target < len(tasks):
            self.region_cursor = target
            return
        # Overflowed the list in the move direction: step to the adjacent
        # region and anchor the cursor to that region's first row.
        self.cycle_region(1 if delta > 0 else -1)

    def cycle_region(self, direction: int) -> int:
        """Advance the focused region one step in ``direction`` (``Tab`` model).

        Walks the ordered :attr:`REGIONS` tuple so ``Tab`` (``direction=+1``)
        moves grid -> Due -> No-due and ``Shift+Tab`` (``direction=-1``) walks
        the reverse. Stepping *past the last* region (``direction=+1`` from
        No-due) or *before the first* (``direction=-1`` from the grid) returns
        ``direction`` without changing :attr:`focus_region` so the caller
        (the app's Tab cycle) can hand focus to / from the shared details
        pane - the grid/Due/No-due regions and the details pane together form
        the full cycle. On a successful in-view step the task cursor is reset
        to the start of the newly focused list (:meth:`_clamp_region_cursor`),
        so entering a list always lands on its first row.

        Args:
            direction: ``+1`` to advance (``Tab``), ``-1`` to reverse
                (``Shift+Tab``).

        Returns:
            ``0`` when the region changed within the view; ``direction`` when
            the step fell off either end (the app then moves to / from the
            details pane).
        """
        index = self.REGIONS.index(self.focus_region)
        target = index + (1 if direction > 0 else -1)
        if target < 0 or target >= len(self.REGIONS):
            return direction
        self.focus_region = self.REGIONS[target]
        self.region_cursor = 0
        self._clamp_region_cursor()
        return 0

    def set_focus_region(self, region: int) -> None:
        """Set the focused region directly and reset the task cursor.

        Used by the app's Tab cycle to re-enter the grid region when focus
        returns from the details pane. Resets :attr:`region_cursor` to the
        start of the newly focused list.

        Args:
            region: One of :attr:`REGION_GRID` / :attr:`REGION_DUE` /
                :attr:`REGION_NO_DUE`.
        """
        self.focus_region = region
        self.region_cursor = 0
        self._clamp_region_cursor()

    def region_tasks(self) -> list[dict[str, Any]]:
        """Return the task list backing the focused list region.

        Looks the focused :attr:`focus_region` up in the data-driven
        :attr:`REGION_TASK_SOURCES` map and calls its bound accessor, so
        adding a region needs only a new map entry (no branching here).

        Returns:
            The selected day's due tasks for :attr:`REGION_DUE`, the no-due
            bucket for :attr:`REGION_NO_DUE`, or an empty list for the grid
            region (which has no per-task cursor) or any unmapped region.
        """
        source = self.REGION_TASK_SOURCES.get(self.focus_region)
        if source is None:
            return []
        return source(self)

    def _clamp_region_cursor(self) -> None:
        """Clamp :attr:`region_cursor` into the focused list's row range.

        Keeps the task cursor valid after a rebuild (a task may have left the
        bucket) or a region change. For the grid region - which has no
        per-task cursor - the cursor is pinned to 0. An empty list also pins
        the cursor to 0 so :meth:`selected_id` reports no selection.
        """
        tasks = self.region_tasks()
        if not tasks:
            self.region_cursor = 0
            return
        self.region_cursor = max(0, min(len(tasks) - 1, self.region_cursor))

    def select_id(self, task_id: str) -> bool:
        """Focus the region/day holding ``task_id`` and put the cursor on it.

        Scans the bucketed :attr:`buckets` for a task with that display id:

        * a task in a *dated* bucket re-targets :attr:`selected` to that day,
          focuses the :attr:`REGION_DUE` list, and points
          :attr:`region_cursor` at the task (so the day's "Due" list highlights
          it);
        * a task in the :attr:`NO_DUE_KEY` bucket focuses the
          :attr:`REGION_NO_DUE` list and points the cursor at it.

        The app re-renders the view via
        :meth:`~doxtr_doto.cli.tui.app.DotoApp._rebuild_alt_views` after this,
        which re-clamps the cursor and scrolls, so no new scrolling logic is
        introduced here. See :meth:`AltLayoutView.select_id` for the overall
        contract.

        Args:
            task_id: The display id (bare or namespaced) to select.

        Returns:
            True when a task with ``task_id`` was found and selected, False
            otherwise.
        """
        for key, items in self.buckets.items():
            for index, task in enumerate(items):
                if str(task.get("id", "")) == task_id:
                    if key == self.NO_DUE_KEY:
                        self.focus_region = self.REGION_NO_DUE
                    else:
                        self.selected = key
                        try:
                            day = _date.fromisoformat(key)
                            self.year, self.month = day.year, day.month
                        except ValueError:
                            pass
                        self.focus_region = self.REGION_DUE
                    self.region_cursor = index
                    return True
        return False

    def assign_task_id(self) -> str | None:
        """Return the highlighted No-due task's id, or None (Feature C).

        Surfaces the task the assign-due key (``A``) acts on: the task under
        the cursor in the :attr:`REGION_NO_DUE` list. Returns None in any
        other region or when the no-due list is empty, so the app can make the
        assign key a documented no-op.

        Returns:
            The highlighted undated task's id, or None.
        """
        if self.focus_region != self.REGION_NO_DUE:
            return None
        tasks = self.region_tasks()
        if not tasks or not 0 <= self.region_cursor < len(tasks):
            return None
        tid = str(tasks[self.region_cursor].get("id", ""))
        # A task missing an id would yield "", which must not reach the
        # update path as a blank id; surface None (no task) instead.
        return tid or None

    def grid_line_count(self) -> int:
        """Return how many content lines the month grid occupies.

        The grid region is the header lines (:attr:`GRID_HEADER_LINES`) plus
        one line per week row of the rendered ``(year, month)``. This is the
        fixed region :meth:`scroll_to_cursor` keeps pinned at the top so the
        month header and week rows never scroll off (Feature 3). Returns 0
        before the grid is populated.

        Returns:
            The number of content lines the grid (header + week rows) spans.
        """
        if not self.year or not self.month:
            return 0
        weeks = _calendar.Calendar().monthdayscalendar(self.year, self.month)
        return self.GRID_HEADER_LINES + len(weeks)

    def scroll_to_cursor(self) -> None:
        """Keep the month grid pinned at the top of the viewport.

        Overrides the shared smart-scroll (:meth:`AltLayoutView.scroll_to_cursor`)
        for the calendar. Grid-region navigation (``h``/``l`` and ``j``/``k``
        while the grid is focused) only ever moves the selector *within* the
        month grid, which spans the first :meth:`grid_line_count` content
        lines; keeping those lines visible is what Feature 3 requires. (In the
        Due / No-due regions ``j``/``k`` move :attr:`region_cursor` within the
        detail list below the grid, but the whole view is still clamped to the
        top so the grid stays pinned.) The view wraps a single
        :class:`~textual.widgets.Static` rendering the grid and the per-day
        detail list together, so scrolling the container by any positive
        offset would push the grid header off the top - the grid cannot be
        pinned while the detail region below it scrolls independently without
        splitting them into two widgets. The honest behavior is therefore to
        clamp the scroll so the whole grid stays visible: the largest offset
        that still shows every grid line (down to line 0) is 0, so the view
        stays at the top. A no-op until the view is mounted.
        """
        if not self.is_mounted:
            return
        # The grid occupies the first ``grid_line_count`` content lines and
        # must stay fully visible. With the grid and the per-day detail list
        # rendered into one Static, scrolling the container moves them
        # together, so the only offset that keeps the grid's top line (content
        # line 0) on screen is 0 - any positive offset hides the header.
        # grid is anchored at content line 0, so the deepest offset keeping it
        # visible is 0 (independent of grid height, so a taller grid from a
        # child theme is still pinned to the top).
        target = 0
        self.scroll_to(y=target, animate=False)

    def ensure_cursor_visible(self) -> None:
        """Keep the pinned month grid visible after a discontinuous selection.

        Overrides the shared :meth:`AltLayoutView.ensure_cursor_visible` so the
        calendar's discontinuous-jump reposition stays consistent with its
        pinned-grid :meth:`scroll_to_cursor`. This override is reached when a
        layout cycle lands on the calendar
        (:meth:`DotoApp._cycle_layout` calls ``_active_view().ensure_cursor_visible()``):
        it must not scroll the grid header off the top. Note the calendar's own
        day move (:meth:`move_day`) and :meth:`select_id` reach their scroll
        through the subsequent rebuild's :meth:`scroll_to_cursor`, not this
        seam - they only mutate selection state and rely on
        :meth:`DotoApp._rebuild_alt_views` to re-render and re-pin the grid.
        Because the grid and the per-day detail list render into a single
        :class:`~textual.widgets.Static`, the only offset that keeps the grid's
        top line (content line 0) on screen is 0, exactly as
        :meth:`scroll_to_cursor` documents - so this delegates to it rather
        than running the span-clamp target computation the list/kanban views
        use. A no-op until the view is mounted.
        """
        self.scroll_to_cursor()

    def selected_tasks(self) -> list[dict[str, Any]]:
        """Return the tasks due on the currently selected day.

        Returns:
            The task dicts bucketed under the selected ISO date (empty when
            none).
        """
        return list(self.buckets.get(self.selected, []))

    def selected_id(self) -> str | None:
        """Return the id of the active region's selected task, if any.

        Which task is "selected" depends on the focused :attr:`focus_region`:

        * :attr:`REGION_GRID` - the calendar's primary selection is a *day*;
          for the shared TUI details/task-time machinery (which expects a
          single task id) this surfaces the *first* task due on the selected
          day (the original behavior), or None when the day has no tasks.
        * :attr:`REGION_DUE` - the task highlighted (:attr:`region_cursor`) in
          the "Due <date>" list, so ``e`` / ``Enter`` / done act on it
          (Feature A).
        * :attr:`REGION_NO_DUE` - the highlighted task in the "No due date"
          list, so ``Enter`` reveals and ``e`` edits that undated task
          (Feature B).

        Returns:
            The selected task's id for the active region, or None.
        """
        if self.focus_region == self.REGION_GRID:
            tasks = self.selected_tasks()
            if not tasks:
                return None
            return str(tasks[0].get("id", ""))
        tasks = self.region_tasks()
        if not tasks or not 0 <= self.region_cursor < len(tasks):
            return None
        return str(tasks[self.region_cursor].get("id", ""))

    @classmethod
    def bucket_by_due(cls, tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group tasks by their due date (ISO ``YYYY-MM-DD``).

        Tasks whose ``due`` field is missing, empty, or unparseable are
        collected under :attr:`NO_DUE_KEY` so an undated task never crashes
        the view and is still shown (in the "no due date" bucket). Within each
        day's list the active (time-recorded) task is pinned to the top via
        :func:`pin_active_first` (Feature A), stable otherwise.

        Args:
            tasks: The task dicts to bucket.

        Returns:
            A mapping of ISO date string (or :attr:`NO_DUE_KEY`) to the tasks
            due that day.
        """
        buckets: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            raw = task.get("due")
            key = cls.NO_DUE_KEY
            if raw:
                try:
                    key = _date.fromisoformat(str(raw)[:10]).isoformat()
                except ValueError:
                    key = cls.NO_DUE_KEY
            buckets.setdefault(key, []).append(task)
        # Feature A: pin the active (time-recorded) task to the top of each
        # day's list (and the no-due bucket), stable otherwise.
        return {key: pin_active_first(items) for key, items in buckets.items()}

    @classmethod
    def format_calendar(
        cls,
        buckets: dict[str, list[dict[str, Any]]],
        selected: str,
        year: int,
        month: int,
    ) -> str:
        """Return the month-grid markup, marking days with due tasks.

        Args:
            buckets: The due-date buckets from :meth:`bucket_by_due`.
            selected: The selected ISO date.
            year: The year the grid shows.
            month: The month the grid shows.

        Returns:
            Textual markup for the month calendar grid.
        """
        header = styled(f"{_calendar.month_name[month]} {year}", "bold")
        weekdays = "Mo Tu We Th Fr Sa Su"
        lines = [header, weekdays]
        for week in _calendar.Calendar().monthdayscalendar(year, month):
            cells: list[str] = []
            for day in week:
                if day == 0:
                    cells.append("  ")
                    continue
                iso = _date(year, month, day).isoformat()
                label = f"{day:2d}"
                has_tasks = bool(buckets.get(iso))
                if iso == selected:
                    cells.append(f"[reverse]{label}[/reverse]")
                elif has_tasks:
                    cells.append(styled(label, "bold reverse"))
                else:
                    cells.append(label)
            lines.append(" ".join(cells))
        return "\n".join(lines)

    @classmethod
    def format_day_detail(
        cls,
        buckets: dict[str, list[dict[str, Any]]],
        selected: str,
        active_region: int = REGION_GRID,
        region_cursor: int = 0,
    ) -> str:
        """Return the detail markup for the selected day plus the no-due list.

        The two lists - the selected day's "Due" tasks and the always-shown
        "No due date" bucket - render each task through :meth:`format_entry`.
        When the focused region (``active_region``) is one of those two lists,
        the task at ``region_cursor`` is passed ``highlighted=True`` so the
        active-region cursor is marked (Features A/B). The highlight markup
        lives entirely in :meth:`format_entry`, so a child theme controls it
        by overriding that seam rather than this method.

        Args:
            buckets: The due-date buckets from :meth:`bucket_by_due`.
            selected: The selected ISO date.
            active_region: The focused region (:attr:`REGION_GRID` /
                :attr:`REGION_DUE` / :attr:`REGION_NO_DUE`). Defaults to the
                grid so a bare call (e.g. a pure-logic test) renders with no
                task highlighted, matching the pre-region behavior.
            region_cursor: The task cursor within the focused list; ignored
                unless ``active_region`` is the Due or No-due list.

        Returns:
            Textual markup listing the selected day's tasks and the
            always-shown "no due date" bucket, with the active-region task
            highlighted.
        """
        lines: list[str] = [styled(f"Due {selected}", "bold")]
        day_tasks = buckets.get(selected, [])
        due_active = active_region == cls.REGION_DUE
        if day_tasks:
            for index, task in enumerate(day_tasks):
                lines.append(
                    cls.format_entry(task, highlighted=due_active and index == region_cursor)
                )
        else:
            lines.append("[dim](nothing due)[/dim]")
        undated = buckets.get(cls.NO_DUE_KEY, [])
        no_due_active = active_region == cls.REGION_NO_DUE
        lines.append("")
        lines.append(styled(f"No due date ({len(undated)})", "bold"))
        if undated:
            for index, task in enumerate(undated):
                lines.append(
                    cls.format_entry(task, highlighted=no_due_active and index == region_cursor)
                )
        else:
            lines.append("[dim](none)[/dim]")
        return "\n".join(lines)

    @classmethod
    def format_entry(cls, task: dict[str, Any], highlighted: bool = False) -> str:
        """Return one task's calendar-detail line.

        The single overridable seam for a task row in the Due / No-due lists,
        so a child theme controls both the row markup *and* how the
        active-region cursor is highlighted by overriding this one method.

        Args:
            task: A task dict.
            highlighted: Whether this task is the active region's cursor
                (Features A/B). Defaults to False so a bare call renders an
                un-highlighted row, matching the pre-region behavior.

        Returns:
            Textual markup for the task entry (wrapped in ``[reverse]`` when
            highlighted).
        """
        status = task.get("status") or ""
        status_cell = styled(status or "-", status_style(status))
        task_id = escape_markup(task.get("id", ""))
        title = cls.escape_title(task.get("title", ""))
        line = f"  [bold]{task_id}[/bold] {status_cell} {title}"
        if highlighted:
            return f"[reverse]{line}[/reverse]"
        return line


class TimeView(AltLayoutView):
    """Time-management view of the global work clock (``time`` layout).

    This is the ``time`` TUI layout
    (:attr:`doxtr_doto.enums.TuiLayout.TIME`): unlike the task-centric
    list/kanban/calendar views, it renders the *global work clock* - every day
    that has one or more work-clock intervals, newest first, each with its
    start/stop intervals and that day's gross / auto-deducted break / net
    totals - plus a grand total across all shown days at the top. It is the
    read-oriented companion to the ``t`` work-time manager modal
    (:class:`doxtr_doto.cli.tui.time_mgmt.WorkTimeScreen`): ``j``/``k`` (or the
    up/down arrows) move the day cursor and ``Enter`` opens that manager for
    the selected day so intervals can be added / edited / deleted, while this
    view shows the resulting totals.

    Break deduction reuses the same :mod:`doxtr_doto.work_report` math the
    ``doto report`` command uses, so the net figures here agree with the CLI
    report. Rendering is delegated to the pure, overridable
    :meth:`format_days` / :meth:`format_day` classmethods so a child theme can
    replace it by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.time_view_class`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the time view with no days and a zeroed cursor."""
        super().__init__(*args, **kwargs)
        #: The worked days (dates with >= 1 interval), newest first.
        self.days: list[_date] = []
        #: Per-day computed figures, keyed by ISO date, mirroring ``days``.
        self._day_work: dict[str, Any] = {}
        #: Per-day interval display rows (start, stop) keyed by ISO date.
        self._day_rows: dict[str, list[tuple[str, str]]] = {}
        #: The highlighted day index into :attr:`days`.
        self.cursor: int = 0
        #: Grand total gross/break/net seconds across the shown days.
        self._totals: tuple[int, int, int] = (0, 0, 0)

    # TimeView deliberately diverges from AltLayoutView.rebuild: it rebuilds
    # from the global work clock's worklog intervals (not the task set), so the
    # parameter is intentionally worklogs rather than tasks. It is always
    # called directly via ``time_view_class``, never polymorphically through
    # the AltLayoutView interface, so the Liskov divergence is safe.
    def rebuild(  # type: ignore[override]
        self,
        worklogs: list[WorkLog],
        breaks: list[Any] | None = None,
        now: _datetime | None = None,
    ) -> None:
        """Rebuild the view from the global work clock's intervals.

        Groups the intervals by the local calendar date they start on (newest
        first), computing each day's gross / break / net via
        :func:`doxtr_doto.work_report.compute_day` so the net figures match the
        CLI ``doto report``. The day cursor is preserved by date across
        rebuilds when the day still has intervals.

        Args:
            worklogs: The global work clock's worklog intervals.
            breaks: Configured breaks (``BreakConfig``-like) to auto-deduct;
                an unparseable break time is skipped so the view never crashes.
            now: Reference "now" for open intervals (defaults to local now).
        """
        from doxtr_doto.time_tracking import parse_timestamp
        from doxtr_doto.work_report import BreakSpec, compute_day

        moment = now if now is not None else _datetime.now().astimezone()
        specs: list[Any] = []
        for cfg in breaks or []:
            try:
                specs.append(BreakSpec.from_config(cfg))
            except (ValueError, TypeError):
                continue

        # Group intervals by their local start date, newest day first.
        by_day: dict[_date, list[tuple[str, str]]] = {}
        for log in worklogs:
            started_raw = log.get("started_at")
            if not started_raw:
                continue
            try:
                day = parse_timestamp(str(started_raw)).date()
            except (ValueError, TypeError):
                continue
            stop = log.get("stopped_at")
            stop_display = str(stop) if stop else "(running)"
            by_day.setdefault(day, []).append((str(started_raw), stop_display))

        previous = self.selected_day()
        self.days = sorted(by_day.keys(), reverse=True)
        self._day_rows = {d.isoformat(): rows for d, rows in by_day.items()}
        self._day_work = {}
        gross_total = brk_total = net_total = 0
        for day in self.days:
            work = compute_day(worklogs, day, specs, moment)
            self._day_work[day.isoformat()] = work
            gross_total += work.gross_seconds
            # Surface the real recorded break time (clock-out gaps the user
            # actually took) rather than any nominal auto-deduction, so the
            # time view reflects breaks that happened at any time of day.
            brk_total += work.recorded_break_seconds
            net_total += work.net_seconds
        self._totals = (gross_total, brk_total, net_total)

        if previous is not None and previous in self.days:
            self.cursor = self.days.index(previous)
        else:
            self.cursor = min(self.cursor, max(len(self.days) - 1, 0))

        self.update_content(
            self.format_days(
                self.days,
                self._day_rows,
                self._day_work,
                self._totals,
                self.cursor,
            )
        )
        self._sync_scroll_anchor()
        self.scroll_to_cursor()

    def selected_day(self) -> _date | None:
        """Return the highlighted day, or None when there are no worked days.

        Returns:
            The highlighted :class:`datetime.date`, or None.
        """
        if not self.days:
            return None
        if self.cursor < 0 or self.cursor >= len(self.days):
            return None
        return self.days[self.cursor]

    def selected_id(self) -> str | None:
        """Return the highlighted day as an ISO string (the view's selection).

        The alt-view contract keys selection by a string id; here that is the
        selected day's ISO date, which the app passes to the work-time manager
        on ``Enter``. Returns None when there are no worked days.

        Returns:
            The highlighted day's ISO date string, or None.
        """
        day = self.selected_day()
        return day.isoformat() if day is not None else None

    def move_cursor(self, delta: int) -> None:
        """Move the highlighted day by ``delta`` (clamped to the day list).

        Args:
            delta: Number of days to move in the list (negative moves up, i.e.
                toward more recent days since the list is newest-first).
        """
        if not self.days:
            return
        self.cursor = max(0, min(len(self.days) - 1, self.cursor + delta))
        self.update_content(
            self.format_days(
                self.days,
                self._day_rows,
                self._day_work,
                self._totals,
                self.cursor,
            )
        )
        self.scroll_to_cursor()

    def move_cursor_to_edge(self, to_bottom: bool) -> None:
        """Jump the highlighted day to the first / last day (``Shift+Up``/down).

        Snaps :attr:`cursor` to ``0`` (the newest day, top of the list) or the
        last day (bottom), then re-renders the day blocks with the new cursor
        (mirroring :meth:`move_cursor`) and re-anchors the smart-scroll
        baseline (:meth:`_sync_scroll_anchor`) so the discontinuous jump
        scrolls to the landing day correctly. A no-op when no days are
        recorded.

        Args:
            to_bottom: Jump to the last day when True, the first when False.
        """
        if not self.days:
            return
        self.cursor = len(self.days) - 1 if to_bottom else 0
        self.update_content(
            self.format_days(
                self.days,
                self._day_rows,
                self._day_work,
                self._totals,
                self.cursor,
            )
        )
        self._sync_scroll_anchor()
        self.scroll_to_cursor()

    def cursor_line(self) -> int:
        """Return the content line the highlighted day's block starts on.

        Each day renders as a fixed block (:meth:`format_day`) preceded by the
        grand-total header; summing the heights of the header and the day
        blocks above the cursor keeps the smart-scroll
        (:meth:`~AltLayoutView.scroll_to_cursor`) landing on the selected day.

        Returns:
            The highlighted day's 0-based starting content line.
        """
        line = self.HEADER_LINES
        for index in range(min(self.cursor, len(self.days))):
            day = self.days[index]
            rows = self._day_rows.get(day.isoformat(), [])
            line += self.day_height(len(rows))
        return line

    def cursor_span(self) -> int:
        """Return how many content lines the highlighted day block spans.

        Returns:
            The selected day's block height (>= 1).
        """
        day = self.selected_day()
        if day is None:
            return 1
        rows = self._day_rows.get(day.isoformat(), [])
        return self.day_height(len(rows))

    #: Content lines the grand-total header (:meth:`format_header`) emits
    #: before the first day block: the ``Work time`` title, the total line and
    #: a trailing blank. A child theme changing the header must keep this in
    #: sync so :meth:`cursor_line` measures correctly.
    HEADER_LINES: int = 3

    @classmethod
    def day_height(cls, interval_count: int) -> int:
        """Return how many content lines a day's block occupies.

        A day block is: the day header line, one line per interval (at least
        one placeholder line when a day somehow has none), the totals line and
        a trailing blank separator.

        Args:
            interval_count: The number of intervals shown for the day.

        Returns:
            The day block's height in content lines.
        """
        return 1 + max(1, interval_count) + 1 + 1

    @classmethod
    def format_header(cls, totals: tuple[int, int, int]) -> str:
        """Return the grand-total header markup.

        Args:
            totals: ``(gross, break, net)`` seconds across the shown days,
                where ``break`` is the real recorded break (clock-out gap)
                time, not a nominal auto-deduction.

        Returns:
            Textual markup for the header (title + total line + blank).
        """
        gross, brk, net = totals
        total = (
            f"Gross {format_duration(gross)}   "
            f"Breaks {format_duration(brk)}   "
            f"[b]Net {format_duration(net)}[/b]"
        )
        return styled("Work time", "bold") + "\n" + total + "\n"

    @classmethod
    def format_days(
        cls,
        days: list[_date],
        day_rows: dict[str, list[tuple[str, str]]],
        day_work: dict[str, Any],
        totals: tuple[int, int, int],
        cursor: int,
    ) -> str:
        """Return the whole time-view markup (header + per-day blocks).

        Args:
            days: Worked days, newest first.
            day_rows: Per-day interval ``(start, stop)`` display rows.
            day_work: Per-day computed figures keyed by ISO date.
            totals: Grand ``(gross, break, net)`` seconds.
            cursor: Index of the highlighted day.

        Returns:
            Textual markup for the view (an empty-state line when no days).
        """
        if not days:
            return cls.format_header(totals) + "\n[dim]No work-clock time recorded.[/dim]"
        blocks = [cls.format_header(totals)]
        for index, day in enumerate(days):
            iso = day.isoformat()
            blocks.append(
                cls.format_day(
                    day,
                    day_rows.get(iso, []),
                    day_work.get(iso),
                    index == cursor,
                )
            )
        return "\n".join(blocks)

    @classmethod
    def format_day(
        cls,
        day: _date,
        rows: list[tuple[str, str]],
        work: Any,
        highlighted: bool,
    ) -> str:
        """Return one worked day's block markup.

        Args:
            day: The calendar day.
            rows: The day's interval ``(start, stop)`` display rows.
            work: The day's :class:`doxtr_doto.work_report.DayWork`, or None.
            highlighted: Whether this day is under the cursor.

        Returns:
            Textual markup for the day block (header, intervals, totals, blank).
        """
        heading = day.strftime("%a %Y-%m-%d")
        header = styled(heading, "bold reverse" if highlighted else "bold")
        lines = [header]
        if rows:
            for start, stop in rows:
                lines.append(f"  {start}  \u2192  {stop}")
        else:
            lines.append("  [dim](no intervals)[/dim]")
        if work is not None:
            # "Breaks" shows recorded clock-out gaps, which are already
            # excluded from gross and are NOT subtracted to reach net (net is
            # reduced only by opt-in auto-deductions). So Gross - Breaks need
            # not equal Net; the three figures are independent.
            lines.append(
                "  "
                + styled(
                    f"Gross {format_duration(work.gross_seconds)}   "
                    f"Breaks {format_duration(work.recorded_break_seconds)}   "
                    f"Net {format_duration(work.net_seconds)}",
                    "dim",
                )
            )
        else:
            lines.append("")
        lines.append("")
        return "\n".join(lines)


#: Monday-first weekday abbreviations (title-case display labels), derived from
#: the canonical :data:`doxtr_doto.constants.WEEKDAY_ABBR` tuple so the ordering
#: cannot drift from the lowercase parse-match set in
#: :mod:`doxtr_doto.cli.tui.time_mgmt` (both share one source of truth).
#: Indexed by Python's :meth:`datetime.date.weekday` convention (Monday=0 ..
#: Sunday=6).
_WEEKDAY_ABBR: tuple[str, ...] = WEEKDAY_ABBR


def weekday_range_label(workweek_days: list[int]) -> str:
    """Return a human-readable label for a set of workweek weekday numbers.

    Pure (no Textual, no I/O) so it is directly unit-testable. Weekday numbers
    use Python's Monday=0 .. Sunday=6 convention. A contiguous run (e.g.
    ``[0, 1, 2, 3, 4]``) collapses to an en-dash range (``"Mon–Fri"``);
    otherwise the abbreviations are listed in weekday order joined by commas
    (e.g. ``[0, 2, 4]`` -> ``"Mon, Wed, Fri"``). A single day shows just that
    abbreviation; an empty set shows ``"(none)"``.

    Args:
        workweek_days: Weekday numbers (any order; de-duplicated and sorted
            here) in the ``0..6`` range.

    Returns:
        A compact label describing the weekday set.
    """
    days = sorted({d for d in workweek_days if 0 <= d <= 6})
    if not days:
        return "(none)"
    if len(days) == 1:
        return _WEEKDAY_ABBR[days[0]]
    contiguous = days == list(range(days[0], days[-1] + 1))
    if contiguous:
        return f"{_WEEKDAY_ABBR[days[0]]}\u2013{_WEEKDAY_ABBR[days[-1]]}"
    return ", ".join(_WEEKDAY_ABBR[d] for d in days)


def workweek_net_seconds(
    worklogs: list[WorkLog],
    specs: list[Any],
    now: _datetime,
    workweek_days: list[int],
) -> int:
    """Return the net work seconds for the current work week.

    Sums the net seconds of each worked day in the ISO week containing
    ``now`` whose weekday (``DayWork.day.weekday()``) is in ``workweek_days``.
    Reuses :func:`doxtr_doto.work_report.compute_period` over
    :func:`~doxtr_doto.work_report.week_range` so the break/net math matches
    the rest of the app (no re-implementation). Pure (no Textual, no I/O).

    Args:
        worklogs: The global work clock's worklog intervals.
        specs: Normalized :class:`doxtr_doto.work_report.BreakSpec` list.
        now: Reference "now"; its local date anchors the week.
        workweek_days: Weekday numbers (Monday=0 .. Sunday=6) that count as
            the work week.

    Returns:
        The summed net seconds across the matching days of the current week.
    """
    from doxtr_doto.work_report import compute_period

    allowed = {d for d in workweek_days if 0 <= d <= 6}
    start, end = week_range(now.date())
    period = compute_period(worklogs, start, end, specs, now)
    return sum(day.net_seconds for day in period.days if day.day.weekday() in allowed)


class WorkTimeSummary(Static):
    """Right-side summary panel for the ``time`` layout.

    Companion to :class:`TimeView`: while the time view lists every worked day
    on the left, this panel renders a compact gross / break / net summary for
    three pre-computed groups on the right - **This week**, **This month**, and
    **This year** - each anchored on the local today. The groups themselves
    live in the class-level :attr:`SUMMARY_GROUPS` tuple (the override seam, so
    a child theme can add/replace a group without touching the computation),
    and the figures reuse
    :func:`doxtr_doto.work_report.compute_period` over
    :func:`~doxtr_doto.work_report.week_range` /
    :func:`~doxtr_doto.work_report.month_range` /
    :func:`~doxtr_doto.work_report.year_range`, with the same breaks the day
    view auto-deducts, so the net totals agree with both the day view and the
    CLI ``doto report``.

    Below the groups the panel also renders a configurable **Work week** net
    total: the sum of net seconds over the current week's days whose weekday
    is in the configured ``workweek_days`` set (Monday=0 .. Sunday=6,
    defaulting to Monday-Friday). It is rendered via the separate overridable
    :meth:`format_workweek` classmethod (its own seam, since it is a distinct
    concept from the gross/break/net groups) using the pure
    :func:`workweek_net_seconds` and :func:`weekday_range_label` helpers.

    Rendering is delegated to the pure, overridable :meth:`format_summary` /
    :meth:`format_group` / :meth:`format_workweek` classmethods (and
    :meth:`summary_data` loops over :attr:`SUMMARY_GROUPS` to compute each
    ``(gross, break, net)`` triple) so a child theme can replace it by
    subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.work_time_summary_class`. The panel
    is only shown in the ``time`` layout (hidden otherwise, like the alt-views).
    """

    #: The summary groups rendered in the panel, as ``(label, range_fn)``
    #: pairs in display order. ``range_fn`` maps the anchor date (local today)
    #: to the inclusive ``(start, end)`` period for that group, reusing the
    #: shared :mod:`doxtr_doto.work_report` range helpers so the net totals
    #: agree with the day view and the CLI report. This is the override seam
    #: for the groups: a child theme can subclass and replace this one tuple
    #: (e.g. add a "This quarter" row, or reorder) without touching
    #: :meth:`summary_data`, which simply loops over it. The three defaults
    #: (This week / This month / This year, each anchored on the local today)
    #: are unchanged.
    SUMMARY_GROUPS: tuple[tuple[str, Callable[[_date], tuple[_date, _date]]], ...] = (
        ("This week", lambda today: week_range(today)),
        ("This month", lambda today: month_range(today)),
        ("This year", lambda today: year_range(today.year)),
    )

    def rebuild(
        self,
        worklogs: list[WorkLog],
        breaks: list[Any] | None = None,
        now: _datetime | None = None,
        workweek_days: list[int] | None = None,
    ) -> None:
        """Recompute the week/month/year summaries and re-render the panel.

        Args:
            worklogs: The global work clock's worklog intervals.
            breaks: Configured breaks (``BreakConfig``-like) to auto-deduct;
                an unparseable break time is skipped so the panel never crashes.
            now: Reference "now" for open intervals (defaults to local now).
            workweek_days: Weekday numbers (Python's Monday=0 .. Sunday=6) that
                count as the configurable "work week" for the work-week net
                total. Defaults to
                :data:`doxtr_doto.cli.global_state.DEFAULT_WORKWEEK_DAYS`
                (Monday-Friday) so existing callers that pass only
                ``(worklogs, breaks)`` keep the historical behavior.
        """
        from doxtr_doto.work_report import BreakSpec

        moment = now if now is not None else _datetime.now().astimezone()
        days = list(workweek_days) if workweek_days is not None else list(DEFAULT_WORKWEEK_DAYS)
        specs: list[Any] = []
        for cfg in breaks or []:
            try:
                specs.append(BreakSpec.from_config(cfg))
            except (ValueError, TypeError):
                continue
        data = self.summary_data(worklogs, specs, moment)
        workweek_net = workweek_net_seconds(worklogs, specs, moment, days)
        self.update(self.format_summary(data, workweek_net, days))

    @classmethod
    def summary_data(
        cls,
        worklogs: list[WorkLog],
        specs: list[Any],
        now: _datetime,
    ) -> list[tuple[str, tuple[int, int, int]]]:
        """Compute the week/month/year ``(gross, break, net)`` summary triples.

        Pure (no Textual, no I/O) so it is directly unit-testable. Each group
        in :attr:`SUMMARY_GROUPS` is computed with
        :func:`doxtr_doto.work_report.compute_period` over its range of the
        local today, reusing the shared break math. Overriding
        :attr:`SUMMARY_GROUPS` (the override seam) changes which groups are
        rendered without touching this method.

        Args:
            worklogs: The global work clock's worklog intervals.
            specs: Normalized :class:`doxtr_doto.work_report.BreakSpec` list.
            now: Reference "now"; its local date anchors every group.

        Returns:
            A list of ``(label, (gross, break, net))`` triples, one per
            :attr:`SUMMARY_GROUPS` entry (by default ``This week`` /
            ``This month`` / ``This year``).
        """
        from doxtr_doto.work_report import compute_period

        today = now.date()
        out: list[tuple[str, tuple[int, int, int]]] = []
        for label, range_fn in cls.SUMMARY_GROUPS:
            start, end = range_fn(today)
            period = compute_period(worklogs, start, end, specs, now)
            # Report the real recorded break (clock-out gap) time, not a
            # nominal auto-deduction, so the summary reflects breaks actually
            # taken at any time of day.
            out.append(
                (
                    label,
                    (period.gross_seconds, period.recorded_break_seconds, period.net_seconds),
                )
            )
        return out

    @classmethod
    def format_summary(
        cls,
        data: list[tuple[str, tuple[int, int, int]]],
        workweek_net_seconds: int | None = None,
        workweek_days: list[int] | None = None,
    ) -> str:
        """Return the whole summary-panel markup (title + per-group blocks).

        Args:
            data: The ``(label, (gross, break, net))`` triples from
                :meth:`summary_data`.
            workweek_net_seconds: The current work-week net total (seconds).
                When None the work-week line is omitted so existing callers
                that pass only ``data`` keep the historical layout.
            workweek_days: Weekday numbers (Monday=0 .. Sunday=6) backing the
                work-week total, used to render its range label. Defaults to
                :data:`doxtr_doto.cli.global_state.DEFAULT_WORKWEEK_DAYS`.

        Returns:
            Textual markup for the panel.
        """
        blocks = [styled("Summary", "bold")]
        for label, totals in data:
            blocks.append(cls.format_group(label, totals))
        if workweek_net_seconds is not None:
            days = list(workweek_days) if workweek_days is not None else list(DEFAULT_WORKWEEK_DAYS)
            blocks.append(cls.format_workweek(workweek_net_seconds, days))
        return "\n".join(blocks)

    @classmethod
    def format_workweek(cls, net_seconds: int, workweek_days: list[int]) -> str:
        """Return the work-week net-total block markup.

        This is a separate concept from the gross/break/net groups in
        :attr:`SUMMARY_GROUPS`, so it has its own overridable classmethod seam
        (a child theme can subclass and replace it without touching the group
        rendering). The weekday-range label is derived from the pure
        :func:`weekday_range_label` helper (contiguous Mon-Fri -> ``Mon–Fri``;
        otherwise the abbreviations are listed).

        Args:
            net_seconds: The work-week net total in seconds.
            workweek_days: Weekday numbers (Monday=0 .. Sunday=6) that count
                as the work week, used for the range label.

        Returns:
            Textual markup for the work-week total line.
        """
        label = weekday_range_label(workweek_days)
        return (
            "\n"
            + styled(f"Work week ({label})", "bold")
            + "\n  "
            + styled(f"Net    {format_duration(net_seconds)}", "bold")
        )

    @classmethod
    def format_group(cls, label: str, totals: tuple[int, int, int]) -> str:
        """Return one summary group's block markup.

        Args:
            label: The group label (e.g. ``"This week"``).
            totals: The group's ``(gross, break, net)`` seconds.

        Returns:
            Textual markup for the group (heading + gross/break/net lines).
        """
        gross, brk, net = totals
        return (
            "\n"
            + styled(label, "bold")
            + "\n"
            + f"  Gross  {format_duration(gross)}\n"
            + f"  Breaks {format_duration(brk)}\n"
            + "  "
            + styled(f"Net    {format_duration(net)}", "bold")
        )
