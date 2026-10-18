"""The Textual application for the doto 3-pane TUI.

This module imports ``textual`` directly and is only loaded when the optional
``textual`` dependency is installed (guarded by
:data:`doxtr_doto.cli.tui.TEXTUAL_AVAILABLE`). It wires together the data
helpers (:mod:`doxtr_doto.cli.tui.data`), the mutating actions
(:mod:`doxtr_doto.cli.tui.actions`), and the modular widgets
(:mod:`doxtr_doto.cli.tui.widgets`).

All mutations route through :mod:`doxtr_doto.cli.tui.actions`, which in turn
reuses the CLI verb functions, so the TUI never duplicates business logic.
Rendering stays modular: the widget classes expose ``format_*`` classmethods
and can be subclassed or swapped by a child app overriding the
:attr:`DotoApp.repo_tree_class`, :attr:`DotoApp.task_list_class`,
:attr:`DotoApp.task_details_class`, and :attr:`DotoApp.status_line_class`
attributes (plus :attr:`DotoApp.task_time_line_class` for the top-right
elapsed-time display). The modal screens are likewise swappable through
:attr:`DotoApp.kickstart_screen_class` and
:attr:`DotoApp.edit_task_screen_class`. The edit modal's priority/status
control is the overridable, type-to-filter :class:`FilterableSelect`
(swappable via :attr:`EditTaskScreen.select_class`), backed by the pure,
render-independent :func:`filter_options` helper.

Navigation keybindings work consistently across every layout. ``j``/``k`` and
the ``down``/``up`` arrows move the cursor within a column/list, and
``Shift+Up``/``Shift+Down`` jump the cursor to the first/last entry of the
current list (in the kanban layout, the first/last card of the *current* swim
lane, mirroring :meth:`DotoApp._jump_cursor` through the overridable
:meth:`doxtr_doto.cli.tui.widgets.AltLayoutView.move_cursor_to_edge` seam).
``h``/``l`` and the ``left``/``right`` arrows drive the per-layout left/right
move: in the kanban layout they *navigate the selection* across the swim lanes
(status columns) without changing any task, in the calendar layout they select
the previous/next day, and they are a harmless no-op in the table/list layouts.
``Enter`` reveals the
currently selected task's details: in the list, kanban and calendar layouts it
opens a *card viewer* popup (:class:`CardViewerScreen`) listing the task's full
detail - the style-markup field lines wrap and the task body renders as
Markdown in a full-height, scrollable body region - and in the table layout it
reveals the details
in the shared details pane (routed through
:meth:`DotoApp.action_activate`, plus :meth:`DotoApp.on_data_table_row_selected`
for the table layout, whose :class:`~textual.widgets.DataTable` consumes
``Enter`` itself). The alternative (list/kanban/calendar) layouts are
scrollable - each is a :class:`doxtr_doto.cli.tui.widgets.AltLayoutView`
(a scroll container) that scrolls to keep the highlighted row visible as the
cursor moves, using the shared smart-scroll algorithm (a configurable margin
trigger + jump; see :attr:`AltLayoutView.SCROLL_MARGIN` /
:attr:`AltLayoutView.SCROLL_JUMP`) for continuous ``j``/``k`` navigation. After
a *discontinuous* selection change - switching swim lanes (``h``/``l``),
selecting a task by id, a calendar day move, or a layout cycle (``v``/``V``)
that re-selects a task - the active view instead repositions via
:meth:`AltLayoutView.ensure_cursor_visible` so the whole selected item is
always brought back on screen (e.g. switching from the bottom of a long
``open`` lane to a one-card ``in-progress`` lane scrolls the viewport up so the
selected card is visible), rather than relying on the now-stale move
direction. The kanban board lays its status columns
out left-to-right with framed, fixed-size *square* cards (constrained in both
width and height, the body clipped with an ellipsis when it overflows); the
selected card is marked by a highlighted *frame*, ``Enter`` opens the card
viewer popup, and ``e`` from that popup opens the edit dialog. The calendar
keeps its month grid
pinned while only the task list below scrolls. In the kanban layout ``Tab``
*moves the selected card* one swim lane forward (to the next status column, a
status change) and ``Shift+Tab`` moves it one lane back - the role the
left/right arrows used to hold; the move is a no-op at the lane edges or into
the ``(other)`` column (no wrap). In the calendar layout ``Tab`` cycles focus
through the view's three regions and the details pane - the month grid, the
"Due" task list, the "No due date" task list, then the shared details pane,
and back to the grid - so the user can navigate from a selected day into its
due tasks (and the undated bucket) to edit / close / reveal them; ``j``/``k``
move the per-task cursor within the focused list (and keep moving a week in
the grid), ``Enter``/``e`` act on the highlighted task, and ``A`` assigns the
selected calendar day as the highlighted no-due task's due date (routed through
:func:`doxtr_doto.cli.tui.actions.update_task`). ``Shift+Tab`` walks the exact
reverse of the ``Tab`` cycle in every layout (table repo-tree -> details ->
task-list; kanban the card one lane back; calendar the region/details cycle in
reverse), routed through :meth:`DotoApp.action_cycle_pane_reverse`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.suggester import Suggester, SuggestFromList
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    Select,
    SelectionList,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option

from doxtr_doto.calsync import resolve
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.id_resolver import namespaced_id as namespaced
from doxtr_doto.cli.output import build_task_detail_lines
from doxtr_doto.cli.session import render_time_spent_line
from doxtr_doto.cli.tui import TERMINAL_TITLE, actions, calsync_tui, data, filtersort, nudge
from doxtr_doto.cli.tui.theme import escape_markup, escape_title
from doxtr_doto.cli.tui.time_mgmt import (
    BreaksConfigScreen,
    TaskSessionsScreen,
    TaskTimeStatsScreen,
    WorkStatsScreen,
    WorkTimeScreen,
)
from doxtr_doto.cli.tui.widgets import (
    AltLayoutView,
    CalendarView,
    KanbanView,
    KeyHintBar,
    ListView,
    RepoTree,
    StatusLine,
    TaskDetails,
    TaskList,
    TaskTimeLine,
    TimeView,
    TitleHighlight,
    WorkTimeSummary,
    weekday_range_label,
)
from doxtr_doto.constants import STATUS_LABELS
from doxtr_doto.enums import SetParentResult, TuiLayout
from doxtr_doto.fields import BY_NAME
from doxtr_doto.raci import RACI_ROLE_LABELS, render_raci_differing_lines

if TYPE_CHECKING:
    from datetime import date, time
    from pathlib import Path

    from doxtr_doto.cli.config import DotoConfig
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.repo_registry import DiscoveredRepo
    from doxtr_doto.cli.tui.add_series_fields import SeriesFormValues
    from doxtr_doto.cli.tui.edit_series_fields import EditSeriesFormValues
    from doxtr_doto.cli.tui.filtersort import ViewPrefs

#: How often (seconds) the live status-line counters refresh.
COUNTER_INTERVAL = 1.0


def _apply_modal_width(modal: Widget, terminal_width: int, width_percent: int) -> None:
    """Size ``modal`` to ``width_percent`` percent of the terminal width.

    Shared by the task pop-ups (:class:`CardViewerScreen`,
    :class:`EditTaskScreen`, :class:`EditBodyScreen`) so they size identically
    from the configurable ``tui_modal_width_ratio``. The width is set as an
    explicit cell count derived from the live terminal width (rather than a
    CSS percentage, whose base is the modal's padded container, not the whole
    terminal), and is re-applied on terminal resize via each screen's
    ``on_resize``. The height is left untouched.

    Args:
        modal: The modal's root container widget to resize.
        terminal_width: The current terminal width in cells
            (``self.app.size.width``).
        width_percent: The target width as a percentage of the terminal width.
    """
    modal.styles.width = max(1, round(terminal_width * width_percent / 100))


def _standalone_modifier_keys() -> frozenset[str]:
    """Return the key names Textual emits for a *bare* modifier keypress.

    On terminals that speak the Kitty keyboard protocol, pressing a modifier
    on its own (e.g. tapping ``Shift`` before typing ``?``) delivers a real
    key event - ``left_shift`` / ``right_shift`` / ``left_control`` / ... -
    *before* the modified key arrives. The two-key stream dispatcher
    (:meth:`DotoApp.on_key`) must ignore these so a pending prefix survives
    until the actual second key lands (otherwise ``t`` then ``Shift``+``?``
    loses the ``t`` prefix on the ``Shift`` event and opens the top-level help
    instead of the time-domain help).

    The set is seeded from Textual's own ``MODIFIER_FUNCTIONAL_KEYS`` when that
    (private) module is importable, and always includes the bare ``shift`` /
    ``ctrl`` / ``alt`` / ``meta`` / ``super`` / ``hyper`` tokens as a defensive
    fallback, so the guard works regardless of the Textual version or the
    terminal's keyboard protocol.
    """
    base = {"shift", "ctrl", "control", "alt", "meta", "super", "hyper"}
    try:
        from textual._keyboard_protocol import MODIFIER_FUNCTIONAL_KEYS

        base |= set(MODIFIER_FUNCTIONAL_KEYS)
    except Exception:  # pragma: no cover - private module may move/rename
        pass
    return frozenset(base)


#: Key names for a bare modifier keypress; ignored while resolving a stream
#: prefix so e.g. the ``Shift`` tapped before ``?`` does not clear the prefix.
MODIFIER_KEYS: frozenset[str] = _standalone_modifier_keys()

#: Pattern used to split option values into words for the type-to-filter
#: matching used by :class:`FilterableSelect` / :func:`filter_options`.
_WORD_SPLIT_RE = re.compile(r"[^0-9a-zA-Z]+")


def filter_options(options: list[str], query: str) -> list[str]:
    """Return the options whose any *word* starts with ``query``.

    This is the pure, render-independent matching helper that backs the
    type-to-filter / letter-select behavior of :class:`FilterableSelect`. Each
    option value is split on runs of non-alphanumeric separators (e.g. ``-``
    or spaces) into words; an option matches when at least one of its words
    starts with ``query`` (case-insensitive). This means typing ``"progress"``
    matches ``"in-progress"`` (the word ``"progress"`` starts with the query)
    and typing ``"c"`` matches ``"critical"``.

    Args:
        options: The candidate option values (the configured status/priority
            strings).
        query: The typed query buffer. An empty/whitespace-only query matches
            everything, so the caller shows the full option list.

    Returns:
        The subset of ``options`` that match, in their original order. An
        empty query returns all options unchanged.
    """
    needle = query.strip().lower()
    if not needle:
        return list(options)
    matches: list[str] = []
    for option in options:
        words = [w for w in _WORD_SPLIT_RE.split(option.lower()) if w]
        if any(word.startswith(needle) for word in words):
            matches.append(option)
    return matches


def substring_filter(options: list[str], query: str) -> list[str]:
    """Return the options containing ``query`` as a case-insensitive substring.

    The free-text matcher backing the :class:`SetParentScreen` search box.
    Unlike :func:`filter_options` (which matches only on word prefixes), this
    matches anywhere in the option, so typing a hyphenated task id
    (``"T-003"``), a fragment of the title, or any contiguous run of
    characters narrows the candidate list the way a general search box is
    expected to. An empty/whitespace-only query returns every option.

    Args:
        options: The candidate option strings (the ``id  title`` labels).
        query: The typed query buffer.

    Returns:
        The subset of ``options`` that contain ``query``, in original order.
    """
    needle = query.strip().lower()
    if not needle:
        return list(options)
    return [option for option in options if needle in option.lower()]


def build_repo_options(
    repos: list[DiscoveredRepo],
    current: DiscoveredRepo,
) -> list[tuple[str, str]]:
    """Build the ``(label, value)`` options for the add-task repo selector.

    This is the pure, render-independent helper that backs
    :meth:`AddTaskScreen.repo_options`. The current repository is always listed
    first (and labelled with a ``(current)`` suffix) so the selector can
    default to it, followed by every cached repository that is not the current
    one. Repos are de-duplicated by their absolute ``path`` so a current repo
    that also appears in the discovery cache is only shown once. Each option's
    *value* is the repository's absolute path, which
    :meth:`AddTaskScreen.repo_for_value` maps back to a
    :class:`~doxtr_doto.cli.repo_registry.DiscoveredRepo`.

    Args:
        repos: The cached repositories (from
            :func:`doxtr_doto.cli.tui.data.list_repos`).
        current: The current working directory's repository (from
            :func:`doxtr_doto.cli.tui.data.current_repo`).

    Returns:
        A list of ``(label, value)`` tuples, current repo first, with values
        being repo paths. When ``current`` is the only repository the list has
        a single entry so the selector still defaults sensibly.
    """
    options: list[tuple[str, str]] = [(f"{current.name} (current)", current.path)]
    seen = {current.path}
    for repo in repos:
        if repo.path in seen:
            continue
        seen.add(repo.path)
        options.append((repo.name, repo.path))
    return options


def _all_repo_known_names_paths(ctx: DotoContext) -> list[Path]:
    """Return the ``known_names.json`` path for every reachable repository.

    The known-names memory store is kept *per repo* (next to each repo's
    ``.doto/tasks.json``), so a suggestion list built from only the current
    repo's store would miss names/tags learned in sibling repos. This resolves
    the memory-store path for the current repo plus every cached repository in
    the registry (:func:`list_repos`), de-duplicated by resolved path, so the
    TUI can offer suggestions drawn from *all* repos the user works across -
    mirroring the GLOBAL task view in :func:`gather_tasks`.

    Args:
        ctx: The CLI context (store + config + global state).

    Returns:
        The de-duplicated list of ``known_names.json`` paths, current repo
        first. Paths are not required to exist; the loaders treat a missing
        file as empty.
    """
    from pathlib import Path

    from doxtr_doto.cli.repo_registry import DOTO_MARKER

    paths: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(path)

    # The current repo's store may not be in the cached registry, so seed it
    # from the active config (mirrors known_names.get_known_names_path()).
    try:
        current = ctx.config.get_json_path().parent / "known_names.json"
        _add(current)
    except Exception:
        pass
    for repo in data.list_repos(ctx):
        _add(Path(repo.path) / DOTO_MARKER.parent / "known_names.json")
    return paths


def _all_repo_stores(ctx: DotoContext) -> list[JsonTaskStore]:
    """Return a task store for the current repo plus every cached repository.

    Companion to :func:`_all_repo_known_names_paths` for the *task-derived*
    half of the suggestion lists: names/tags already in use on tasks are
    gathered from every reachable repo, not just the current one, so
    suggestions span all repos like the GLOBAL task view does.

    Args:
        ctx: The CLI context.

    Returns:
        The task stores to scan, current repo first, de-duplicated by the
        store's resolved ``.doto/tasks.json`` path.
    """
    stores: list[JsonTaskStore] = [ctx.store]
    seen: set[Path] = set()
    try:
        seen.add(ctx.config.get_json_path().resolve())
    except Exception:
        pass
    for repo in data.list_repos(ctx):
        store = data.store_for_repo(repo)
        try:
            key = store.path.resolve()
        except Exception:
            key = None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        stores.append(store)
    return stores


def known_assignee_names(ctx: DotoContext) -> list[str]:
    """Return the known assignee names for suggestion in the TUI.

    Merges the names remembered in the per-repo known-names memory stores
    (:mod:`doxtr_doto.cli.known_names`) with the distinct assignees already
    present on tasks, aggregated across **every** reachable repository (the
    current repo plus the cached registry) rather than only the current one -
    so suggestions include names typed in previous sessions and names in use
    in sibling repos, matching the TUI's cross-repo (GLOBAL) task view. The
    result is sorted case-insensitively and de-duplicated case-insensitively.

    Args:
        ctx: The CLI context (store + config), used to read tasks across repos
            and resolve the memory-store paths.

    Returns:
        The sorted, de-duplicated list of candidate assignee names.
    """
    from doxtr_doto.cli import known_names

    by_lower: dict[str, str] = {}
    for store in _all_repo_stores(ctx):
        try:
            tasks = store.get_all_tasks().values()
        except Exception:
            continue
        for task in tasks:
            assignee = task.get("assignee")
            if assignee:
                by_lower[assignee.lower()] = assignee
    for path in _all_repo_known_names_paths(ctx):
        for name in known_names.get_assignees(path=path):
            by_lower[name.lower()] = name
    return sorted(by_lower.values(), key=lambda s: s.lower())


def known_tag_names(ctx: DotoContext) -> list[str]:
    """Return the known tag names for suggestion in the TUI.

    Merges the tags remembered in the per-repo known-names memory stores with
    the distinct tags already present on tasks, aggregated across **every**
    reachable repository (current repo plus the cached registry), mirroring
    :func:`known_assignee_names`. This is what lets the tags field suggest
    tags from sibling repos and not just the repo doto was launched in.

    Args:
        ctx: The CLI context (store + config).

    Returns:
        The sorted, de-duplicated list of candidate tag names.
    """
    from doxtr_doto.cli import known_names

    by_lower: dict[str, str] = {}
    for store in _all_repo_stores(ctx):
        try:
            tasks = store.get_all_tasks().values()
        except Exception:
            continue
        for task in tasks:
            for tag in task.get("tags", []):
                by_lower[tag.lower()] = tag
    for path in _all_repo_known_names_paths(ctx):
        for name in known_names.get_tags(path=path):
            by_lower[name.lower()] = name
    return sorted(by_lower.values(), key=lambda s: s.lower())


class TagSuggester(Suggester):
    """Suggest completions for the *last* tag in a comma-separated input.

    The TUI tags field is a single comma-separated :class:`~textual.widgets.Input`
    (e.g. ``"frontend, bu"``). A plain prefix suggester would try to match the
    whole buffer, so this suggester instead splits off the segment after the
    final comma, prefix-matches it against ``tags`` (case-insensitively), and
    returns the full buffer with that final segment completed. This keeps the
    already-entered tags intact while completing only the one being typed.

    Args:
        tags: The candidate tag names, in suggestion priority order.
    """

    def __init__(self, tags: list[str]) -> None:
        """Store the candidate tags for case-insensitive matching."""
        super().__init__(case_sensitive=False)
        self._tags = list(tags)

    async def get_suggestion(self, value: str) -> str | None:
        """Complete the final comma-separated segment of ``value``.

        Args:
            value: The current (casefolded) input buffer.

        Returns:
            The buffer with its final tag segment completed, or None when the
            final segment is empty or matches nothing. The leading whitespace
            of the final segment is preserved so ``"a, b"`` completes cleanly.
        """
        head, sep, tail = value.rpartition(",")
        segment = tail.strip()
        if not segment:
            return None
        for tag in self._tags:
            if tag.lower().startswith(segment.lower()):
                leading = tail[: len(tail) - len(tail.lstrip())]
                return f"{head}{sep}{leading}{tag}"
        return None


class AddTaskResult(NamedTuple):
    """The outcome of the add-task modal.

    Dismissed by :class:`AddTaskScreen` when the user submits a non-empty
    title; an empty title (or ``Escape``) cancels and dismisses ``None``
    instead, so a non-``None`` result always carries a usable title.

    The modal is field-configurable (see
    :mod:`doxtr_doto.cli.tui.add_fields`): the ``minimal`` preset collects only
    ``title`` + ``repo`` (the original behavior), while the ``default`` / ``all``
    presets (or an explicit field list) collect the additional optional fields
    below. Every optional field defaults to ``None`` so a result built by the
    minimal path is unchanged, and :meth:`DotoApp.action_add` can forward every
    field unconditionally.

    Attributes:
        title: The entered task title (already stripped, never empty).
        repo: The repository the task should be created in (the current repo
            by default, or whichever the user picked in the selector).
        assignee: Assignee name, or None when the field was absent/empty.
        priority: Priority value, or None.
        status: Status value, or None.
        due: Parsed due date (``YYYY-MM-DD`` / ``...THH:MM``), or None.
        estimate: Estimate in whole minutes, or None.
        tags: Comma-separated tags string, or None.
        depends_on: Comma-separated dependency IDs, or None.
        body: Task body/description, or None.
        progress: Progress percentage (0-100), or None.
        raci: Explicit RACI string (``"responsible alice, ..."``), or None.
    """

    title: str
    repo: DiscoveredRepo
    assignee: str | None = None
    priority: str | None = None
    status: str | None = None
    due: str | None = None
    estimate: int | None = None
    tags: str | None = None
    depends_on: str | None = None
    body: str | None = None
    progress: int | None = None
    raci: str | None = None


class KillRing:
    """A tiny shared kill buffer backing bash-style kill/yank across fields.

    A single instance is shared by every :class:`KillRingInput` and
    :class:`KillRingTextArea` in a modal (see :data:`_KILL_RING`), so text
    killed with ``Ctrl-K`` in one field can be yanked with ``Ctrl-Y`` into
    another - including across the single-line Title/Assignee/Tags inputs and
    the multi-line Body text area.

    This is intentionally a single-entry buffer (the most recent kill), not a
    full readline kill ring with rotation; ``Ctrl-K`` with an empty kill
    leaves the stored text untouched so a stray kill does not clobber content
    the user still wants to yank.
    """

    def __init__(self) -> None:
        """Initialize an empty kill buffer."""
        self.text: str = ""

    def kill(self, text: str) -> None:
        """Store ``text`` as the kill buffer, ignoring empty kills.

        Args:
            text: The text just removed by a kill. Empty strings are ignored
                so an end-of-line kill does not clobber the buffer.
        """
        if text:
            self.text = text

    def yank(self) -> str:
        """Return the current kill buffer (empty string when nothing killed)."""
        return self.text


#: Process-wide shared kill ring so kill/yank works across every field in the
#: edit modal (single-line inputs and the multi-line body text area alike).
_KILL_RING = KillRing()


class KillRingInput(Input):
    """A single-line :class:`textual.widgets.Input` with bash-style kill/yank.

    Adds readline / bash-style *kill and yank* to the standard input:

    * ``Ctrl-K`` deletes from the cursor to the end of the line (as the base
      :class:`~textual.widgets.Input` already does) but first captures the
      removed text into the shared :data:`_KILL_RING`, and
    * ``Ctrl-Y`` yanks (inserts) the most recently killed text at the cursor.

    Because the kill ring is shared (see :class:`KillRing`), text killed here
    can be yanked into any other kill-ring field in the same modal, including
    the multi-line :class:`KillRingTextArea` body. When ``Ctrl-K`` is pressed
    with no text to the right of the cursor the buffer is left unchanged.
    """

    #: Yank (Ctrl-Y) in addition to the base Input bindings. ``ctrl+k`` is
    #: already bound by :class:`~textual.widgets.Input` to
    #: ``delete_right_all``, which we override below to capture the kill text.
    BINDINGS = [("ctrl+y", "yank", "Yank killed text")]

    #: The shared kill ring. Overridable so a child theme can scope kills
    #: differently; defaults to the module-wide :data:`_KILL_RING`.
    kill_ring: KillRing = _KILL_RING

    def action_delete_right_all(self) -> None:
        """Kill to end of line, capturing the removed text into the kill ring.

        Mirrors bash's ``Ctrl-K``: the text from the cursor to the end of the
        line (or the current selection, matching the base widget) is removed
        and stored in the shared :data:`_KILL_RING` so it can later be yanked
        with :meth:`action_yank` from this or any other kill-ring field. An
        empty kill (nothing to the right of the cursor) leaves the existing
        buffer untouched.
        """
        if self.selection.is_empty:
            killed = self.value[self.cursor_position :]
        else:
            start, end = sorted(self.selection)
            killed = self.value[start:end]
        self.kill_ring.kill(killed)
        super().action_delete_right_all()

    def action_yank(self) -> None:
        """Insert the kill ring's text at the cursor (bash ``Ctrl-Y``).

        A no-op when the kill ring is empty.
        """
        text = self.kill_ring.yank()
        if text:
            self.insert_text_at_cursor(text)


class KillRingTextArea(TextArea):
    """A multi-line :class:`textual.widgets.TextArea` with bash-style kill/yank.

    Shares the same :data:`_KILL_RING` as :class:`KillRingInput`, so text
    killed in the single-line Title/Assignee/Tags inputs can be yanked into
    the body here, and vice-versa:

    * ``Ctrl-K`` deletes from the cursor to the end of the current line (the
      base :class:`~textual.widgets.TextArea` behavior) but first captures the
      removed text into the shared kill ring, and
    * ``Ctrl-Y`` yanks (inserts) the most recently killed text at the cursor.

    An empty kill (cursor already at end of a non-empty line, or an empty
    line) leaves the kill buffer untouched so it does not clobber content the
    user still wants to yank.
    """

    #: Yank (Ctrl-Y) in addition to the base TextArea bindings. ``ctrl+k`` is
    #: already bound by :class:`~textual.widgets.TextArea`, whose action we
    #: override below to capture the killed text.
    BINDINGS = [("ctrl+y", "yank", "Yank killed text")]

    #: The shared kill ring (see :class:`KillRingInput.kill_ring`).
    kill_ring: KillRing = _KILL_RING

    async def action_delete_to_end_of_line_or_delete_line(self) -> None:
        """Kill to end of line, capturing the removed text into the kill ring.

        Captures the text from the cursor to the end of the current line into
        the shared :data:`_KILL_RING` before delegating to the base
        :class:`~textual.widgets.TextArea` kill behavior.
        """
        if self.selection.is_empty:
            start = self.cursor_location
            end = self.get_cursor_line_end_location()
            self.kill_ring.kill(self.get_text_range(start, end))
        else:
            self.kill_ring.kill(self.selected_text)
        await super().action_delete_to_end_of_line_or_delete_line()

    def action_yank(self) -> None:
        """Insert the kill ring's text at the cursor (bash ``Ctrl-Y``).

        A no-op when the kill ring is empty or the text area is read-only.
        """
        text = self.kill_ring.yank()
        if text and not self.read_only:
            self.insert(text)


class FilterScreen(ModalScreen[str | None]):
    """Modal prompting for a task-list filter/search term."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        """Build the modal's widgets."""
        yield Label("Filter tasks (title/id/tag):", id="filter-label")
        yield Input(placeholder="Search term (empty clears)", id="filter-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dismiss with the submitted search term."""
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        """Dismiss the modal, leaving the filter unchanged."""
        self.dismiss(None)


class FilterableSelect(Select[str]):
    """A :class:`textual.widgets.Select` with type-to-filter / letter-select.

    While focused, typing letters narrows the option list using the pure,
    unit-testable :func:`filter_options` helper (word-based prefix matching).
    The behavior is:

    * typing accumulates a query buffer and recomputes the matches,
    * if exactly one option matches, it is selected immediately and the
      buffer is cleared,
    * if more than one matches, the displayed options are narrowed to just
      the matches so the user can pick,
    * if none match, the full option list is kept (the keypress is ignored)
      so the widget never ends up empty,
    * ``Backspace`` shortens the query, and
    * ``Escape`` is *not* swallowed, so the enclosing modal can still cancel.

    The buffer is cleared on blur, whenever a value is selected (including
    picking from the native dropdown), and after a single-match auto-select.
    The full option set is captured at mount time from the initial options
    (label and value) so filtering can always restore the complete list,
    labels included. The class is overridable so a child theme can swap
    matching behavior via :attr:`match_fn`.
    """

    #: The matching function used to filter options. Overridable by subclasses
    #: or child themes; defaults to the module-level :func:`filter_options`.
    #: Overrides must be a ``staticmethod`` (or otherwise not bind ``self``),
    #: since it is invoked as ``self.match_fn(options, query)``; it receives
    #: the list of option *values* and the query buffer, and returns the
    #: matching subset of values.
    match_fn = staticmethod(filter_options)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the select and the empty type-to-filter query buffer."""
        super().__init__(*args, **kwargs)
        self._query: str = ""
        # (label, value) pairs so narrowing/restore preserve display labels
        # even when a child theme uses labels distinct from values.
        self._all_options: list[tuple[Any, Any]] = []

    def on_mount(self) -> None:
        """Capture the full option list (label + value) for filter/restore."""
        self._all_options = [
            (label, value) for label, value in self._options if value is not self.NULL
        ]

    def _option_values(self) -> list[Any]:
        """Return just the captured option values (filter input/matching)."""
        return [value for _label, value in self._all_options]

    def _restore_options(self) -> None:
        """Restore the full option list, preserving labels and current value."""
        current = self.value
        self.set_options(iter(self._all_options))
        if current is not self.NULL and current in self._option_values():
            self.value = current

    def _apply_query(self) -> None:
        """Recompute matches for the current buffer and update the widget.

        Selects the sole match when the query narrows to one option, narrows
        the dropdown to the matches when several remain, and restores the full
        list when the query is empty. A query that matches nothing is treated
        as a no-op (the buffer keeps its previous accepted state). The
        multi-match narrowing preserves the current value when it is still
        among the matches, mirroring :meth:`_restore_options`.
        """
        if not self._query:
            self._restore_options()
            return
        matches = self.match_fn(self._option_values(), self._query)
        if len(matches) == 1:
            self.set_options(iter(self._all_options))
            self.value = matches[0]
            self._query = ""
        elif matches:
            matched = set(matches)
            current = self.value
            self.set_options(
                (label, value) for label, value in self._all_options if value in matched
            )
            if current is not self.NULL and current in matched:
                self.value = current

    def on_key(self, event: Any) -> None:
        """Handle type-to-filter keystrokes while the select is focused.

        Letters/digits extend the query buffer, ``Backspace`` shortens it, and
        any resulting match set is applied via :meth:`_apply_query`. ``Escape``
        is deliberately left unhandled so the modal's cancel binding fires.
        """
        key = event.key
        if key == "escape":
            return
        if key == "backspace":
            if self._query:
                self._query = self._query[:-1]
                event.stop()
                event.prevent_default()
                self._apply_query()
            return
        char = getattr(event, "character", None)
        if char and char.isalnum():
            self._query += char
            event.stop()
            event.prevent_default()
            self._apply_query()

    def _on_blur(self, event: Any) -> None:
        """Clear the query buffer and restore options when focus leaves."""
        self._query = ""
        if self._all_options:
            self._restore_options()
        super()._on_blur(event)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Clear the query buffer when the selected value changes.

        Covers picking a value from the native dropdown while focused, so a
        subsequent keystroke starts a fresh query rather than extending a
        stale buffer. The single-match auto-select path already clears the
        buffer, so re-clearing here is harmless.
        """
        self._query = ""


class ViewPrefsScreen(ModalScreen["ViewPrefs | None"]):
    """Modal to configure the task-list filter + sort preferences (Feature C).

    A pop-up - like :class:`FilterScreen` - bound to ``F`` (Shift+F; the
    lowercase ``f`` is not bound and ``/`` is the free-text filter) that lets
    the user configure the filters and sort used by
    :func:`doxtr_doto.cli.tui.filtersort.apply_view_prefs`:

    Filters:

    * hide completed tasks (status ``done``),
    * hide done tasks completed more than N days ago (the "recent done"
      filter; the N days box seeds from the ``tui_recent_done_days`` config
      default and is independent of "hide completed"),
    * show only tasks due today,
    * show only tasks due this week,
    * show only tasks with a chosen tag (from the known tags), and
    * show only tasks with a chosen priority.
    * show only tasks from one or more selected repositories (the
      ``Repositories`` multi-select). Only meaningful in GLOBAL scope - in
      LOCAL scope the task list is already a single repo, so the repo filter
      is inert - but the control is always shown so it stays usable. Selecting
      no repository keeps every repository's tasks (the GLOBAL "show all"
      state); selecting one or more restricts the list to those repositories.

    Sort-by (single select) with an ascending/descending order: due date,
    priority, tag, or ``next`` (the recommended-next ordering, reusing the
    ``doto next`` scoring via
    :func:`doxtr_doto.cli.tui.filtersort.apply_sort`).

    On submit the modal dismisses with a fresh
    :class:`doxtr_doto.cli.tui.filtersort.ViewPrefs`; ``Escape`` cancels and
    dismisses ``None`` leaving the current prefs unchanged. The modal is
    modular/overridable: a child theme swaps the whole screen via
    :attr:`DotoApp.view_prefs_screen_class`, the sort/filter select widget is
    overridable via :attr:`select_class` (mirroring
    :attr:`EditTaskScreen.select_class`), and the repository multi-select
    widget is overridable via :attr:`repo_select_class`.

    Args:
        prefs: The current preferences to pre-populate the controls with.
        tags: The known tag names offered in the tag selector.
        priorities: The configured priorities offered in the priority
            selector.
        repos: The known repository names offered in the repository
            multi-select. Defaults to an empty list.
        default_recent_done_days: The config-default "recent done" window (in
            days) used to pre-fill the days box when the recent-done filter is
            currently disabled. Defaults to 10.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: Overridable select widget class, mirroring
    #: :attr:`EditTaskScreen.select_class` so a child theme can swap in a
    #: custom (e.g. type-to-filter) :class:`Select` subclass.
    select_class: type[Select[str]] = FilterableSelect

    #: Overridable multi-select widget class for the ``Repositories`` filter.
    #: Defaults to Textual's :class:`~textual.widgets.SelectionList`; a child
    #: theme can swap in a custom multi-select subclass without reimplementing
    #: :meth:`compose`, mirroring :attr:`select_class`.
    repo_select_class: type[SelectionList[str]] = SelectionList

    def __init__(
        self,
        prefs: ViewPrefs,
        tags: list[str],
        priorities: list[str],
        repos: list[str] | None = None,
        default_recent_done_days: int = 10,
    ) -> None:
        """Initialize the modal from the current prefs and known values."""
        super().__init__()
        self.prefs = prefs
        self.tags = list(tags)
        self.priorities = list(priorities)
        self.repos = list(repos or [])
        #: The config-default recent-done window used to pre-fill the days box
        #: when the filter is currently disabled (so enabling it offers a
        #: sensible N rather than an empty field).
        self.default_recent_done_days = default_recent_done_days

    def compose(self) -> ComposeResult:
        """Build the filter + sort controls, pre-populated from the prefs."""
        from doxtr_doto.enums import SortOrder

        with Vertical(id="viewprefs-modal"):
            yield Label("Filter & sort tasks", id="viewprefs-title")
            yield Checkbox(
                "Hide completed tasks",
                value=self.prefs.hide_completed,
                id="viewprefs-hide-completed",
            )
            yield Checkbox(
                "Hide done completed more than N days ago",
                value=self.prefs.recent_done_days is not None,
                id="viewprefs-recent-done",
            )
            yield Label("Recent-done window (days)")
            yield Input(
                value=str(
                    self.prefs.recent_done_days
                    if self.prefs.recent_done_days is not None
                    else self.default_recent_done_days
                ),
                placeholder=str(self.default_recent_done_days),
                id="viewprefs-recent-done-days",
            )
            yield Checkbox(
                "Sync conflicts only",
                value=self.prefs.conflicts_only,
                id="viewprefs-conflicts-only",
            )
            yield Label("Due")
            yield self.select_class(
                [(label, value) for value, label in self._due_options()],
                value=self.prefs.due_filter.value,
                allow_blank=False,
                id="viewprefs-due",
            )
            yield Label("Only tag")
            yield self.select_class(
                [(t, t) for t in self.tags],
                allow_blank=True,
                id="viewprefs-tag",
                **self._optional_value_kwargs(self.prefs.tag_filter, self.tags),
            )
            yield Label("Only priority")
            yield self.select_class(
                [(p, p) for p in self.priorities],
                allow_blank=True,
                id="viewprefs-priority",
                **self._optional_value_kwargs(self.prefs.priority_filter, self.priorities),
            )
            yield Label("Repositories (Global scope)")
            yield self.repo_select_class(
                *self._repo_selections(),
                id="viewprefs-repos",
            )
            yield Label("Sort by")
            yield self.select_class(
                [(label, value) for value, label in self._sort_options()],
                value=self.prefs.sort_key.value,
                allow_blank=False,
                id="viewprefs-sort-key",
            )
            yield Label("Order")
            yield self.select_class(
                [("Ascending", SortOrder.ASC.value), ("Descending", SortOrder.DESC.value)],
                value=self.prefs.sort_order.value,
                allow_blank=False,
                id="viewprefs-sort-order",
            )
            with Horizontal(id="viewprefs-bottom"):
                yield Button("Apply", id="viewprefs-apply", variant="primary")
                yield Button("Reset", id="viewprefs-reset")

    def _repo_selections(self) -> list[tuple[str, str, bool]]:
        """Return the ``(prompt, value, selected)`` repository multi-select rows.

        One row per known repository, with the row pre-checked when the repo is
        already in :attr:`prefs`'s ``repo_filter``. The prompt and value are
        both the repo name so :meth:`collect_prefs` can read the selected names
        back directly.

        Returns:
            The selection rows for the :attr:`repo_select_class` multi-select.
        """
        selected = set(self.prefs.repo_filter)
        return [(repo, repo, repo in selected) for repo in self.repos]

    @staticmethod
    def _due_options() -> list[tuple[str, str]]:
        """Return the ``(value, label)`` options for the due-filter select.

        Derived from the :class:`~doxtr_doto.enums.DueFilter` enum via
        :data:`~doxtr_doto.enums.DUE_FILTER_LABELS` (iterating the enum in
        definition order) so a new member automatically becomes selectable and
        cannot be backend-supported but UI-unselectable.
        """
        from doxtr_doto.enums import DUE_FILTER_LABELS, DueFilter

        return [(member.value, DUE_FILTER_LABELS[member]) for member in DueFilter]

    @staticmethod
    def _sort_options() -> list[tuple[str, str]]:
        """Return the ``(value, label)`` options for the sort-key select.

        Derived from the :class:`~doxtr_doto.enums.SortKey` enum via
        :data:`~doxtr_doto.enums.SORT_KEY_LABELS` (iterating the enum in
        definition order) so a new sort key automatically becomes selectable
        and cannot be backend-supported but UI-unselectable.
        """
        from doxtr_doto.enums import SORT_KEY_LABELS, SortKey

        return [(member.value, SORT_KEY_LABELS[member]) for member in SortKey]

    @staticmethod
    def _optional_value_kwargs(value: str | None, choices: list[str]) -> dict[str, Any]:
        """Return the ``value=`` kwargs for an optional filter select.

        An unselected optional filter must leave the select *blank*. Passing
        :data:`textual.widgets.Select.BLANK` explicitly as ``value=`` is
        rejected by Textual's value validator (the blank sentinel is not a
        legal explicit value), so this returns an empty mapping - letting the
        select default to blank - when ``value`` is not one of ``choices``,
        and only passes ``value=`` for a real selection.

        Args:
            value: The stored filter value, or None.
            choices: The valid choices.

        Returns:
            ``{"value": value}`` when ``value`` is a valid choice, otherwise an
            empty dict (select defaults to blank).
        """
        if value and value in choices:
            return {"value": value}
        return {}

    def collect_prefs(self) -> ViewPrefs:
        """Collect the control values into a fresh :class:`ViewPrefs`.

        The pure assembly of the modal's selections, factored out so it can be
        unit-tested without rendering. An unselected (blank) tag/priority
        selector maps to None (no filter), and the repository multi-select
        maps its checked rows to :attr:`ViewPrefs.repo_filter` (an empty tuple
        when nothing is checked).

        Returns:
            The :class:`doxtr_doto.cli.tui.filtersort.ViewPrefs` the modal
            dismisses with.
        """
        from doxtr_doto.cli.tui.filtersort import ViewPrefs
        from doxtr_doto.enums import DueFilter, SortKey, SortOrder

        hide = self.query_one("#viewprefs-hide-completed", Checkbox).value
        recent_on = self.query_one("#viewprefs-recent-done", Checkbox).value
        recent_days_raw = self.query_one("#viewprefs-recent-done-days", Input).value
        conflicts = self.query_one("#viewprefs-conflicts-only", Checkbox).value
        due_raw = self.query_one("#viewprefs-due", Select).value
        tag_raw = self.query_one("#viewprefs-tag", Select).value
        pri_raw = self.query_one("#viewprefs-priority", Select).value
        sort_raw = self.query_one("#viewprefs-sort-key", Select).value
        order_raw = self.query_one("#viewprefs-sort-order", Select).value
        repos_widget = self.query_one("#viewprefs-repos", SelectionList)
        repo_filter = tuple(str(v) for v in repos_widget.selected)
        tag = tag_raw if isinstance(tag_raw, str) else None
        pri = pri_raw if isinstance(pri_raw, str) else None
        # Recent-done: active only when the box is checked and the days field
        # parses to a positive int; otherwise the filter is disabled (None).
        # A blank/invalid entry while checked falls back to the config default.
        recent_done_days: int | None = None
        if recent_on:
            try:
                parsed_days = int(str(recent_days_raw).strip())
            except ValueError:
                parsed_days = self.default_recent_done_days
            recent_done_days = parsed_days if parsed_days > 0 else None
        return ViewPrefs(
            hide_completed=bool(hide),
            recent_done_days=recent_done_days,
            conflicts_only=bool(conflicts),
            due_filter=DueFilter(due_raw) if isinstance(due_raw, str) else DueFilter.ALL,
            tag_filter=tag or None,
            priority_filter=pri or None,
            sort_key=SortKey(sort_raw) if isinstance(sort_raw, str) else SortKey.NONE,
            sort_order=SortOrder(order_raw) if isinstance(order_raw, str) else SortOrder.ASC,
            repo_filter=repo_filter,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply the collected prefs, or reset them to defaults."""
        from doxtr_doto.cli.tui.filtersort import ViewPrefs

        if event.button.id == "viewprefs-apply":
            self.dismiss(self.collect_prefs())
        elif event.button.id == "viewprefs-reset":
            self.dismiss(ViewPrefs())

    def action_cancel(self) -> None:
        """Dismiss the modal, leaving the current prefs unchanged."""
        self.dismiss(None)


class DetailRatioScreen(ModalScreen["str | None"]):
    """Modal to configure the table-layout detail-pane size ratio.

    A small ``Config`` pop-up (reached via ``c`` -> ``d``) that lets the user
    set how much of the *total* vertical space the lower detail pane takes, as
    an ``"n/d"`` fraction: ``"3/4"`` (the default) gives the detail pane 3/4 of
    the height and the task list the remaining 1/4, ``"1/2"`` splits them
    evenly, ``"5/8"`` gives the detail pane five-eighths, and so on. The
    numerator must be smaller than the denominator. On *Apply* the modal
    dismisses with the (canonicalized) ratio string; ``Escape`` cancels and
    dismisses ``None`` leaving the current ratio unchanged. The caller
    (:meth:`DotoApp.action_configure_detail_ratio`) applies it immediately and
    persists it for the next launch.

    Args:
        ratio: The current ratio to pre-populate the text box with.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, ratio: str) -> None:
        """Initialize the modal from the current detail-pane ratio."""
        super().__init__()
        self.ratio = ratio

    def compose(self) -> ComposeResult:
        """Build the ratio text box and the Apply/Reset buttons."""
        with Vertical(id="detailratio-modal"):
            yield Label("Detail pane size", id="detailratio-title")
            yield Label(
                "How much of the total height the lower detail pane takes,\n"
                "as an n/d fraction (e.g. 3/4 = detail 3/4, task list 1/4)."
            )
            yield Input(
                value=self.ratio,
                placeholder="3/4",
                id="detailratio-input",
            )
            with Horizontal(id="detailratio-bottom"):
                yield Button("Apply", id="detailratio-apply", variant="primary")
                yield Button("Reset", id="detailratio-reset")

    def collect_ratio(self) -> str:
        """Return the entered ratio, canonicalized to a valid ``"n/d"`` string.

        Reads the text box and normalizes it via
        :func:`doxtr_doto.cli.tui.actions.normalize_detail_ratio` so a
        malformed/empty entry falls back to the default rather than breaking
        the layout.

        Returns:
            A canonical ``"n/d"`` detail-ratio string.
        """
        from doxtr_doto.cli.tui.actions import normalize_detail_ratio

        return normalize_detail_ratio(self.query_one("#detailratio-input", Input).value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply the entered ratio, or reset it to the default."""
        from doxtr_doto.cli.tui.actions import DEFAULT_DETAIL_RATIO

        if event.button.id == "detailratio-apply":
            self.dismiss(self.collect_ratio())
        elif event.button.id == "detailratio-reset":
            self.dismiss(DEFAULT_DETAIL_RATIO)

    def action_cancel(self) -> None:
        """Dismiss the modal, leaving the current ratio unchanged."""
        self.dismiss(None)


class ModalWidthScreen(ModalScreen["str | None"]):
    """Modal to configure the task pop-up width ratio.

    A small ``Config`` pop-up (reached via ``c`` -> ``m``) that lets the user
    set how wide the task pop-ups are - the card viewer (``Enter``), the
    edit-task modal (``e``) and the edit-note modal (``n``) - as an ``"n/d"``
    fraction of the *total* terminal width: ``"3/4"`` (the default) makes each
    modal three-quarters of the terminal width, ``"1/2"`` half, ``"1/1"`` full
    width, and so on. The numerator must be positive and no larger than the
    denominator. On *Apply* the modal dismisses with the (canonicalized) ratio
    string; ``Escape`` cancels and dismisses ``None`` leaving the current
    ratio unchanged. The caller (:meth:`DotoApp.action_configure_modal_width`)
    persists it for the next launch.

    Args:
        ratio: The current ratio to pre-populate the text box with.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, ratio: str) -> None:
        """Initialize the modal from the current pop-up width ratio."""
        super().__init__()
        self.ratio = ratio

    def compose(self) -> ComposeResult:
        """Build the ratio text box and the Apply/Reset buttons."""
        with Vertical(id="modalwidth-modal"):
            yield Label("Task pop-up width", id="modalwidth-title")
            yield Label(
                "How wide the task pop-ups (view, edit, note) are,\n"
                "as an n/d fraction of the terminal width (e.g. 3/4)."
            )
            yield Input(
                value=self.ratio,
                placeholder="3/4",
                id="modalwidth-input",
            )
            with Horizontal(id="modalwidth-bottom"):
                yield Button("Apply", id="modalwidth-apply", variant="primary")
                yield Button("Reset", id="modalwidth-reset")

    def collect_ratio(self) -> str:
        """Return the entered ratio, canonicalized to a valid ``"n/d"`` string.

        Reads the text box and normalizes it via
        :func:`doxtr_doto.cli.tui.actions.normalize_modal_width_ratio` so a
        malformed/empty entry falls back to the default rather than breaking
        the layout.

        Returns:
            A canonical ``"n/d"`` modal-width-ratio string.
        """
        from doxtr_doto.cli.tui.actions import normalize_modal_width_ratio

        return normalize_modal_width_ratio(self.query_one("#modalwidth-input", Input).value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply the entered ratio, or reset it to the default."""
        from doxtr_doto.cli.tui.actions import DEFAULT_MODAL_WIDTH_RATIO

        if event.button.id == "modalwidth-apply":
            self.dismiss(self.collect_ratio())
        elif event.button.id == "modalwidth-reset":
            self.dismiss(DEFAULT_MODAL_WIDTH_RATIO)

    def action_cancel(self) -> None:
        """Dismiss the modal, leaving the current ratio unchanged."""
        self.dismiss(None)


class SetParentScreen(ModalScreen["str | None"]):
    """Modal to pick the PARENT task for the selected task(s) (attach feature).

    Opened by the ``e P`` Edit-domain key. Shows a type-to-search box over a
    live-filtered list of candidate parent tasks: the search :attr:`input_class`
    box is focused the moment the modal opens, so the user can **start typing
    immediately** to narrow the list - no need to press Enter / open a dropdown
    first. The list below is an :attr:`option_list_class` that re-filters on
    every keystroke (word-prefix match via :func:`filter_options` on the option
    label). Dismisses with the chosen parent's id (the candidate ``value``) on
    *Apply* / selecting a row / pressing Enter, or ``None`` on *Cancel* /
    ``Escape``.

    The caller (:meth:`DotoApp.action_set_parent`) is responsible for building
    the candidate list - it excludes the child task(s) being parented and any
    task that would create a cycle - and for the "remember last parent"
    behavior: it passes the previously chosen parent as ``default`` so the
    list opens pre-highlighted on it, making it fast to attach several tasks
    to the SAME parent in a row.

    Modular/overridable, mirroring :class:`ViewPrefsScreen`: a child theme
    swaps the whole screen via :attr:`DotoApp.set_parent_screen_class`, the
    search box via :attr:`input_class`, and the candidate list via
    :attr:`option_list_class`. :attr:`select_class` is retained for backward
    compatibility (so existing child themes / the public seam keep working)
    but is no longer used to build the picker.

    Args:
        candidates: The ``(label, value)`` parent options, where ``value`` is
            the task ref the chosen parent is reported back as and ``label`` is
            the human-readable ``id  title`` row.
        default: The value to pre-highlight (the remembered last parent), or
            None to open with no pre-selection. Ignored when it is not among
            the candidate values (e.g. the remembered parent no longer exists
            or is one of the children being parented).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: Retained for backward compatibility with child themes / the public
    #: seam (the picker no longer uses a dropdown, but a theme may still read
    #: or override this). Mirrors :attr:`EditTaskScreen.select_class` /
    #: :attr:`ViewPrefsScreen.select_class`.
    select_class: type[Select[str]] = FilterableSelect

    #: Overridable search-box class. Defaults to :class:`KillRingInput`
    #: (bash-style kill/yank), mirroring :attr:`EditTaskScreen.input_class`.
    #: Focused on mount so the user can type to search immediately.
    input_class: type[Input] = KillRingInput

    #: Overridable candidate-list class. Defaults to Textual's
    #: :class:`~textual.widgets.OptionList`; a child theme can swap in a
    #: custom subclass without reimplementing :meth:`compose`.
    option_list_class: type[OptionList] = OptionList

    #: The pure matching helper used to filter candidates as the user types.
    #: Defaults to the case-insensitive :func:`substring_filter` (a general
    #: free-text search box; matches anywhere in the ``id  title`` label, so
    #: typing a hyphenated id or a fragment of the title works). Overridable
    #: by child themes; mirrors :attr:`FilterableSelect.match_fn`.
    match_fn = staticmethod(substring_filter)

    def __init__(
        self,
        candidates: list[tuple[str, str]],
        default: str | None = None,
    ) -> None:
        """Initialize the picker from the candidate parents + remembered default."""
        super().__init__()
        self.candidates = list(candidates)
        self.default = default
        #: The value currently highlighted in the list (the one *Apply* / Enter
        #: would choose). Seeded from the remembered default when valid.
        values = {value for _label, value in self.candidates}
        self._highlighted_value: str | None = self.default if self.default in values else None

    def _filtered_candidates(self, query: str) -> list[tuple[str, str]]:
        """Return the ``(label, value)`` candidates matching ``query``.

        An empty query returns every candidate; otherwise the word-prefix
        :attr:`match_fn` is applied to the option labels (so typing part of a
        task id or a word in the title narrows the list), preserving the
        original candidate order.
        """
        if not query.strip():
            return list(self.candidates)
        matched_labels = set(self.match_fn([label for label, _v in self.candidates], query))
        return [(label, value) for label, value in self.candidates if label in matched_labels]

    def _populate(self, query: str = "") -> None:
        """(Re)build the option list for ``query`` and restore the highlight.

        The candidate ``value`` is stored as each :class:`Option` id so the
        selection handlers can report the task ref directly. When the
        previously highlighted value is still present it stays highlighted;
        otherwise the first row is highlighted so Enter always has a target.
        """
        option_list = self.query_one("#setparent-list", OptionList)
        filtered = self._filtered_candidates(query)
        option_list.clear_options()
        option_list.add_options([Option(label, id=value) for label, value in filtered])
        values = [value for _label, value in filtered]
        if self._highlighted_value in values:
            option_list.highlighted = values.index(self._highlighted_value)
        elif values:
            option_list.highlighted = 0
            self._highlighted_value = values[0]
        else:
            self._highlighted_value = None

    def compose(self) -> ComposeResult:
        """Build the search box, the live-filtered list, and Apply/Cancel."""
        with Vertical(id="setparent-modal"):
            yield Label("Set parent task", id="setparent-title")
            yield self.input_class(
                placeholder="Type to search tasks...",
                id="setparent-search",
            )
            yield self.option_list_class(id="setparent-list")
            with Horizontal(id="setparent-bottom"):
                yield Button("Apply", id="setparent-apply", variant="primary")
                yield Button("Cancel", id="setparent-cancel")

    def on_mount(self) -> None:
        """Populate the list and focus the search box for immediate typing."""
        self._populate()
        self.query_one("#setparent-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-filter the candidate list live as the search query changes."""
        if event.input.id == "setparent-search":
            self._populate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply the highlighted candidate when Enter is pressed in the search."""
        if event.input.id == "setparent-search":
            self._apply()

    #: Search-box keys forwarded to the candidate list so the user can both
    #: type to filter and navigate the results without leaving the box.
    _LIST_NAV_KEYS = {"up", "down", "pageup", "pagedown", "home", "end"}

    def on_key(self, event: events.Key) -> None:
        """Forward list-navigation keys from the search box to the list.

        The search :attr:`input_class` is focused so the user can type to
        filter immediately; forwarding Up/Down/PageUp/PageDown/Home/End lets
        them move the highlight in the candidate list without tabbing away
        from the search box. Other keys (letters, backspace, Enter, Escape)
        fall through to the normal input / binding handling.
        """
        if self.focused is not self.query_one("#setparent-search", Input):
            return
        if event.key not in self._LIST_NAV_KEYS:
            return
        option_list = self.query_one("#setparent-list", OptionList)
        if option_list.option_count == 0:
            return
        event.stop()
        event.prevent_default()
        if event.key == "up":
            option_list.action_cursor_up()
        elif event.key == "down":
            option_list.action_cursor_down()
        elif event.key == "pageup":
            option_list.action_page_up()  # type: ignore[no-untyped-call]
        elif event.key == "pagedown":
            option_list.action_page_down()  # type: ignore[no-untyped-call]
        elif event.key == "home":
            option_list.action_first()
        elif event.key == "end":
            option_list.action_last()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Track the highlighted candidate so *Apply* / Enter choose it."""
        if event.option_list.id == "setparent-list":
            self._highlighted_value = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dismiss with the selected candidate (click / Enter on the list)."""
        if event.option_list.id == "setparent-list":
            self.dismiss(event.option.id)

    def _apply(self) -> None:
        """Dismiss with the currently highlighted candidate (or None)."""
        self.dismiss(self._highlighted_value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss with the chosen parent id, or cancel."""
        if event.button.id == "setparent-apply":
            self._apply()
        elif event.button.id == "setparent-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss the modal without choosing a parent."""
        self.dismiss(None)


class _TaskFieldWidgetsMixin:
    """Shared field-widget plumbing for the add/edit task modals.

    Both :class:`AddTaskScreen` and :class:`EditTaskScreen` render the same
    kinds of task-field widgets (single-line inputs, a body text area,
    priority/status selects and the RACI role sub-inputs) and parse the same
    date/duration inputs. This mixin factors out the identical pieces so the
    behavior is defined once:

    * the overridable widget classes :attr:`select_class` / :attr:`input_class`
      / :attr:`text_area_class`,
    * the auto-complete suggester seams :meth:`assignee_suggester` /
      :meth:`tags_suggester` / :meth:`raci_suggester`,
    * the input parsers :meth:`parse_due` / :meth:`parse_estimate`, and
    * the RACI role inputs builder :meth:`build_raci_inputs`.

    The RACI role widget ids differ per modal (``add-raci-*`` vs
    ``edit-raci-*``), so each concrete screen keeps its own
    :attr:`RACI_FIELDS` tuple (built with its prefix); :meth:`build_raci_inputs`
    reads that per-subclass attribute, so it works unchanged for both. The
    mixin relies on ``self.known_assignees`` / ``self.known_tags`` being set by
    the concrete screen's ``__init__``.
    """

    #: The concrete screen supplies these candidate lists in ``__init__``.
    known_assignees: list[str]
    known_tags: list[str]
    #: Each concrete screen defines its own RACI field tuple (ids are prefixed
    #: per modal); :meth:`build_raci_inputs` reads this attribute.
    RACI_FIELDS: tuple[tuple[str, str, str], ...]

    #: Overridable select widget class (the type-to-filter priority/status
    #: control). A child theme can swap in a custom :class:`Select` subclass
    #: without reimplementing ``compose``.
    select_class: type[Select[str]] = FilterableSelect

    #: Overridable single-line input class for the text fields. Defaults to
    #: :class:`KillRingInput` (bash-style kill/yank).
    input_class: type[Input] = KillRingInput

    #: Overridable multi-line text-area class for the body field. Defaults to
    #: :class:`KillRingTextArea`.
    text_area_class: type[TextArea] = KillRingTextArea

    def assignee_suggester(self) -> Suggester | None:
        """Return the auto-complete suggester for the assignee input (seam).

        Prefix-matches the :attr:`known_assignees` candidates
        case-insensitively, or None when there are no candidates. Overridable
        by a child theme.
        """
        if not self.known_assignees:
            return None
        return SuggestFromList(self.known_assignees, case_sensitive=False)

    def tags_suggester(self) -> Suggester | None:
        """Return the auto-complete suggester for the tags input (seam).

        A :class:`TagSuggester` completing only the final comma-separated
        segment against :attr:`known_tags`, so already-entered tags are
        preserved, or None when there are no candidates.
        """
        if not self.known_tags:
            return None
        return TagSuggester(self.known_tags)

    def raci_suggester(self) -> Suggester | None:
        """Return the auto-complete suggester for the RACI inputs (seam).

        RACI role fields are comma-separated person names, so the default
        completes the final comma-separated segment against
        :attr:`known_assignees` (mirroring the tags suggester behavior), or
        None when there are no candidate names.
        """
        if not self.known_assignees:
            return None
        return TagSuggester(self.known_assignees)

    @staticmethod
    def parse_due(raw: str) -> str | None:
        """Parse the due-date input via the shared CLI relative-date parser.

        Reuses :func:`doxtr_doto.cli.commands.add.parse_relative_date` (the
        exact parser the ``doto add`` / ``doto update --due`` verbs use) so
        absolute (``YYYY-MM-DD``) and relative (``+7d``, ``friday``, ...) forms
        behave identically in the TUI and CLI. An empty/whitespace input means
        "no due date" and returns None.

        Args:
            raw: The raw due-date input string.

        Returns:
            The normalized ``YYYY-MM-DD`` string, or None.

        Raises:
            ValueError: If the input is non-empty and cannot be parsed. The
                message is suitable for surfacing to the user.
        """
        from doxtr_doto.cli.commands.add import parse_relative_date

        value = raw.strip()
        if not value:
            return None
        return parse_relative_date(value)

    @staticmethod
    def parse_estimate(raw: str) -> int | None:
        """Parse the estimate input into whole minutes (shared CLI parser).

        Reuses :func:`doxtr_doto.date_utils.parse_duration` (the same parser
        the ``:estimate:`` directive option and ``doto update --estimate`` use)
        so the compact duration syntax (``5m``, ``90m``, ``4h``, ``1h30m`` or a
        bare number of minutes) behaves identically in the TUI and CLI. An
        empty/whitespace input returns None.

        Args:
            raw: The raw estimate input string.

        Returns:
            The estimate in whole minutes, or None.

        Raises:
            ValueError: If the input is non-empty and cannot be parsed. The
                message is suitable for surfacing to the user.
        """
        from doxtr_doto.date_utils import parse_duration

        value = raw.strip()
        if not value:
            return None
        return parse_duration(value)

    def build_raci_inputs(self, fields: dict[str, str]) -> list[Widget]:
        """Build the RACI role input widgets (overridable seam).

        Each role gets a labelled comma-separated :class:`Input` pre-populated
        from ``fields[f"raci_{role}"]`` (empty for a new task), reusing the
        :meth:`raci_suggester`. Reads the concrete screen's :attr:`RACI_FIELDS`
        (whose widget ids carry the per-modal prefix). A child theme can
        override this to reshape the RACI region without reimplementing
        ``compose``.

        Args:
            fields: The pre-populated field values (RACI roles keyed
                ``raci_<role>``).

        Returns:
            The ordered list of label/input widgets to yield into the modal.
        """
        widgets: list[Widget] = []
        for role, label, widget_id in self.RACI_FIELDS:
            widgets.append(Label(label))
            widgets.append(
                self.input_class(
                    value=fields.get(f"raci_{role}", ""),
                    id=widget_id,
                    suggester=self.raci_suggester(),
                )
            )
        return widgets


class AddTaskScreen(_TaskFieldWidgetsMixin, ModalScreen["AddTaskResult | None"]):
    """Modal prompting for a new task's fields and its target repository.

    Dismisses with an :class:`AddTaskResult` carrying the entered values and
    the chosen repository, or ``None`` if cancelled (``Escape`` or - in the
    minimal single-field layout - an empty title). The actual task creation is
    performed by the app via :func:`doxtr_doto.cli.tui.actions.add_task` so the
    add logic matches ``doto add``.

    **Configurable fields.** Which fields the modal shows, in what order, is
    driven by config (``tui_add_fields``) and resolved by the pure
    :mod:`doxtr_doto.cli.tui.add_fields` helpers (:func:`resolve_field_names`).
    Three presets are available - ``minimal`` (title only; the default and
    backward-compatible behavior), ``default`` (title, tags, due, assignee,
    body) and ``all`` (every user-settable field, derived dynamically from
    :data:`doxtr_doto.fields.TASK_FIELDS`) - or an explicit list of field names
    overriding a preset. Per-field defaults come from ``tui_add_defaults`` and
    are resolved at modal-open time via
    :func:`doxtr_doto.cli.tui.add_fields.resolve_default` (so a relative ``due``
    like ``tomorrow`` becomes a concrete date).

    **Layout.** The configured field order is the exact top-to-bottom render
    order. The repository selector follows the title (when >1 repo). In the
    single-field ``minimal`` layout the modal keeps its original compact form
    (a title ``Input`` submitted with Enter); any multi-field layout renders
    the fields in a scrolling region with a docked ``Save`` button, mirroring
    :class:`EditTaskScreen`.

    **Overridability (child themes).** The whole screen is swappable via
    :attr:`DotoApp.add_task_screen_class`. Within the screen the widget classes
    are overridable via :attr:`select_class` / :attr:`input_class` /
    :attr:`text_area_class` (mirroring :class:`EditTaskScreen`), the
    field->widget-kind mapping via :attr:`FIELD_KINDS`, the per-kind widget
    builders via the data-driven :attr:`FIELD_KIND_BUILDERS` dispatch table (a
    new render kind is a one-method + one-table-entry change - no ``if``/``elif``
    chain), the field labels via :attr:`FIELD_LABELS`, the RACI sub-fields via
    :attr:`RACI_FIELDS` / :meth:`build_raci_inputs`, the select choices via
    :meth:`select_choices`, and the per-field suggesters via the
    :meth:`field_suggester` dispatch seam (routing to :meth:`assignee_suggester`
    / :meth:`tags_suggester` / :meth:`raci_suggester`). A theme can thus restyle
    one field (or add a new one) without reimplementing :meth:`compose`. The
    ``(label, value)`` repo option list is built by the pure,
    render-independent :func:`build_repo_options` helper.

    **Registering a new field (persistence caveat).** A newly registered
    settable field in :data:`doxtr_doto.fields.TASK_FIELDS` *automatically*
    appears in the ``all`` preset and *renders* (via the default ``input``
    kind, or a mapped :attr:`FIELD_KINDS` kind). Its entered value, however, is
    NOT persisted by registration alone: :meth:`collect_result` maps the
    rendered widgets onto the fixed :class:`AddTaskResult` fields, and the
    create pipeline
    (:class:`AddTaskResult` -> :meth:`DotoApp.action_add` ->
    :func:`doxtr_doto.cli.tui.actions.add_task` ->
    :func:`doxtr_doto.cli.commands.add._build_task_data`) carries only the
    known optional fields. To persist a brand-new field's value, add it to
    :class:`AddTaskResult`, read it in :meth:`collect_result`, forward it in
    :meth:`DotoApp.action_add` + :func:`doxtr_doto.cli.tui.actions.add_task`,
    and store it in :func:`_build_task_data` - the same manual touch-points the
    :mod:`doxtr_doto.fields` module docstring already lists for a new field.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: The widget classes (:attr:`select_class` / :attr:`input_class` /
    #: :attr:`text_area_class`), the suggester seams and the
    #: :meth:`parse_due` / :meth:`parse_estimate` parsers come from
    #: :class:`_TaskFieldWidgetsMixin` (shared with :class:`EditTaskScreen`).

    #: Data-driven field name -> render "kind" mapping. The kind selects which
    #: per-widget builder runs (via :attr:`FIELD_KIND_BUILDERS`) in
    #: :meth:`_build_field`. Each advertised kind is honored by a real builder:
    #:
    #: * ``input`` -- a single-line :attr:`input_class` text field. ``date``
    #:   (``due``), ``duration`` (``estimate``) and ``depends`` (``depends_on``)
    #:   render as a plain input *today* (their values are validated at submit
    #:   via :meth:`parse_due` / :meth:`parse_estimate` / the store) but are
    #:   kept as distinct kinds so a child theme can later override just that
    #:   kind (e.g. a real date picker) by adding a builder method + a
    #:   :attr:`FIELD_KIND_BUILDERS` entry, without editing :meth:`_build_field`.
    #: * ``select`` -- a :attr:`select_class` dropdown (``priority`` / ``status``).
    #: * ``textarea`` -- a multi-line :attr:`text_area_class` (``body``).
    #: * ``tags`` -- a single-line input wired to the tags suggester.
    #: * ``raci`` -- the RACI role sub-inputs (:meth:`build_raci_inputs`).
    #:
    #: A child theme can override this to change how a field renders (or to
    #: wire a newly registered field) in one place. Fields not listed here
    #: fall back to the ``input`` kind.
    FIELD_KINDS: dict[str, str] = {
        "title": "input",
        "assignee": "input",
        "priority": "select",
        "status": "select",
        "due": "date",
        "estimate": "duration",
        "tags": "tags",
        "depends_on": "depends",
        "body": "textarea",
        "progress": "input",
        "raci": "raci",
    }

    #: Data-driven kind -> builder-method-name dispatch table. :meth:`_build_field`
    #: looks up the field's :attr:`FIELD_KINDS` kind here and calls the named
    #: method ``(name, label, fields) -> list[Widget]`` to build its widgets.
    #: A child theme adds a brand-new render kind by defining one builder
    #: method and adding one entry here - no ``if``/``elif`` chain to edit. A
    #: kind missing from this table falls back to the :attr:`_DEFAULT_KIND`
    #: builder (a plain input). The ``date`` / ``duration`` / ``depends`` kinds
    #: deliberately point at the same :meth:`_build_input` builder as ``input``
    #: (they render as a plain input today) while staying distinct kinds, so a
    #: theme can retarget just one of them later.
    FIELD_KIND_BUILDERS: dict[str, str] = {
        "input": "_build_input",
        "date": "_build_input",
        "duration": "_build_input",
        "depends": "_build_input",
        "tags": "_build_input",
        "select": "_build_select_field",
        "textarea": "_build_textarea",
        "raci": "_build_raci",
    }

    #: The render kind used for fields absent from :attr:`FIELD_KINDS`.
    _DEFAULT_KIND = "input"

    #: The RACI role fields rendered when the ``raci`` field is shown, as
    #: ``(role, label, widget_id)`` tuples. Derived from the canonical
    #: :data:`doxtr_doto.raci.RACI_ROLE_LABELS` so adding/renaming a role is a
    #: one-place change in :mod:`doxtr_doto.raci`. Overridable so a child theme
    #: can reorder/relabel the RACI inputs (mirrors
    #: :attr:`EditTaskScreen.RACI_FIELDS`).
    RACI_FIELDS: tuple[tuple[str, str, str], ...] = tuple(
        (role, f"{label} (comma-separated)", f"add-raci-{role}")
        for role, label in RACI_ROLE_LABELS.items()
    )

    #: Human-readable labels for the per-field ``Label`` widget. Overridable
    #: so a child theme can relabel a field in one place (listed in the
    #: class-docstring overridability section). A field without an entry here
    #: falls back to its :data:`doxtr_doto.fields.BY_NAME` ``display_label``.
    FIELD_LABELS: dict[str, str] = {
        "title": "Title",
        "assignee": "Assignee",
        "priority": "Priority",
        "status": "Status",
        "due": "Due (YYYY-MM-DD or +7d, friday)",
        "estimate": "Estimate (e.g. 5m, 90m, 4h, 1h30m)",
        "tags": "Tags (comma-separated)",
        "depends_on": "Dependencies (comma-separated IDs)",
        "body": "Body",
        "progress": "Progress (0-100)",
    }

    def __init__(
        self,
        repos: list[DiscoveredRepo],
        current: DiscoveredRepo,
        *,
        config: DotoConfig | None = None,
        statuses: list[str] | None = None,
        priorities: list[str] | None = None,
        known_assignees: list[str] | None = None,
        known_tags: list[str] | None = None,
    ) -> None:
        """Initialize the add-task modal.

        Args:
            repos: The cached repositories (from
                :func:`doxtr_doto.cli.tui.data.list_repos`) offered in the repo
                selector.
            current: The current working directory's repository (from
                :func:`doxtr_doto.cli.tui.data.current_repo`), used as the
                selector's default.
            config: The active config, used to resolve the field-set preset /
                explicit list (``tui_add_fields``) and per-field defaults
                (``tui_add_defaults``). When None the modal falls back to the
                ``minimal`` preset with no prefilled defaults, preserving the
                original title-only behavior.
            statuses: The configured status choices for a status select.
            priorities: The configured priority choices for a priority select.
            known_assignees: Candidate assignee names for auto-complete
                suggestions.
            known_tags: Candidate tag names for auto-complete suggestions.
        """
        super().__init__()
        self.repos = repos
        self.current = current
        self.config = config
        self.statuses = statuses or []
        self.priorities = priorities or []
        self.known_assignees = known_assignees or []
        self.known_tags = known_tags or []

    def resolve_fields(self) -> tuple[str, ...]:
        """Return the ordered task-field names this modal should render.

        Delegates to the pure
        :func:`doxtr_doto.cli.tui.add_fields.resolve_field_names` using the
        config's ``tui_add_fields`` value (preset name or explicit list),
        falling back to the ``minimal`` preset when no config was supplied.
        The order is the exact top-to-bottom render order.

        Returns:
            The ordered tuple of field names (always starting with ``title``).
        """
        from doxtr_doto.cli.tui import add_fields

        spec = self.config.tui_add_fields if self.config is not None else None
        return add_fields.resolve_field_names(spec)

    def build_fields(self) -> dict[str, str]:
        """Return the initial (resolved-default) string value for each field.

        Each field in :meth:`resolve_fields` gets its resolved default from
        :func:`doxtr_doto.cli.tui.add_fields.resolve_default` (the
        ``tui_add_defaults`` table, with the classic ``default_*`` config
        fallbacks and relative-date resolution). The RACI field expands to its
        four role keys (``raci_responsible`` etc.), which have no configurable
        default and start empty. Pure/testable: no widgets are touched.

        Returns:
            A mapping of field (or RACI-role) key to its prefilled string value.
        """
        from doxtr_doto.cli.config import DotoConfig
        from doxtr_doto.cli.tui import add_fields

        config = self.config if self.config is not None else DotoConfig()
        defaults = config.tui_add_defaults or {}
        values: dict[str, str] = {}
        for name in self.resolve_fields():
            if name == add_fields.REPO_FIELD:
                # The repo selector is a pseudo-field, not a text field: its
                # default is handled by ``default_repo_value()`` and it has no
                # text value in the field map.
                continue
            if name == "raci":
                for role, _label, _wid in self.RACI_FIELDS:
                    values[f"raci_{role}"] = ""
                continue
            values[name] = add_fields.resolve_default(name, defaults, config)
        return values

    def repo_options(self) -> list[tuple[str, str]]:
        """Return the ``(label, value)`` options for the repo selector.

        Delegates to the pure :func:`build_repo_options` helper so the current
        repo is listed first (and defaulted) and the option values are repo
        paths that :meth:`repo_for_value` can resolve back to a
        :class:`~doxtr_doto.cli.repo_registry.DiscoveredRepo`.

        Returns:
            The selector options, current repo first.
        """
        return build_repo_options(self.repos, self.current)

    def default_repo_value(self) -> str:
        """Return the repo-selector value to default-select at modal open.

        Honors a ``repo`` entry in ``tui_add_defaults``: the name is matched
        case-insensitively against the known repos, falling back to a path
        match. An unknown/empty default falls back to the current repo's path
        (the original behavior), so a bad default never surfaces an error.

        Returns:
            The repo path to pre-select in the selector.
        """
        default = ""
        if self.config is not None:
            default = str((self.config.tui_add_defaults or {}).get("repo", "")).strip()
        if not default:
            return self.current.path
        lowered = default.lower()
        if self.current.name.lower() == lowered:
            return self.current.path
        for repo in self.repos:
            if repo.name.lower() == lowered:
                return repo.path
        if self.current.path == default:
            return self.current.path
        for repo in self.repos:
            if repo.path == default:
                return repo.path
        return self.current.path

    def repo_for_value(self, value: str) -> DiscoveredRepo:
        """Resolve a selected option value (a repo path) to its repository.

        Args:
            value: The selected option value, which is a repository path
                produced by :func:`build_repo_options`.

        Returns:
            The matching :class:`~doxtr_doto.cli.repo_registry.DiscoveredRepo`.
            Falls back to the current repo when the value does not match a
            known repository (e.g. the selector is blank), so the result is
            always usable.
        """
        if value == self.current.path:
            return self.current
        for repo in self.repos:
            if repo.path == value:
                return repo
        return self.current

    def field_suggester(self, name: str) -> Suggester | None:
        """Return the auto-complete suggester for a single input field (seam).

        The single dispatch point that wires a field name to its suggester, so
        a child theme can give a new field a suggester (or change an existing
        one) by overriding this method alone rather than reimplementing
        :meth:`_build_input`. The default routes the ``tags`` field to
        :meth:`tags_suggester` and the ``assignee`` field to
        :meth:`assignee_suggester`; every other field gets no suggester. (RACI
        role inputs are wired separately in :meth:`build_raci_inputs`.)

        Args:
            name: The field name being built.

        Returns:
            A :class:`textual.suggester.Suggester` for the field, or None when
            the field has no suggestions.
        """
        if name == "tags":
            return self.tags_suggester()
        if name == "assignee":
            return self.assignee_suggester()
        return None

    def select_choices(self, name: str) -> list[str]:
        """Return the choice list for a ``select``-kind field (seam).

        The default maps ``priority`` to :attr:`priorities` and every other
        select field (e.g. ``status``) to :attr:`statuses`. A child theme can
        override this to supply choices for a new select field without
        reimplementing :meth:`_build_select_field`.

        Args:
            name: The select field name.

        Returns:
            The ordered choice values for the field's dropdown.
        """
        if name == "priority":
            return self.priorities
        return self.statuses

    def _is_minimal(self) -> bool:
        """Return True when the modal shows only the title field.

        The title-only layout keeps the original compact modal (Enter submits,
        no Save button), which is the backward-compatible default.
        """
        return self.resolve_fields() == ("title",)

    def compose(self) -> ComposeResult:
        """Build the modal's widgets from the resolved field list.

        The minimal (title-only) layout renders the original compact form (a
        single title ``Input`` plus the repo selector). Any multi-field layout
        renders each configured field in registered order inside a scrolling
        region with a docked ``Save`` button (mirroring
        :class:`EditTaskScreen`). The repository selector follows the title
        when more than one repo is available.
        """
        if self._is_minimal():
            yield from self._compose_minimal()
            return
        yield from self._compose_full()

    def _compose_minimal(self) -> ComposeResult:
        """Render the original title-only layout (backward compatible).

        Keeps the historical widget ids (``#add-label`` / ``#add-input`` /
        ``#add-repo``) and a plain :class:`~textual.widgets.Input` submitted
        with Enter, so single-field setups behave exactly as before.
        """
        options = self.repo_options()
        yield Label("New task title:", id="add-label")
        yield Input(placeholder="Task title", id="add-input")
        yield from self._build_repo_selector(options)

    def _build_repo_selector(self, options: list[tuple[str, str]]) -> list[Widget]:
        """Build the repository-selector label + dropdown (overridable seam).

        Factored out so both placement paths - the explicit ``repo``-in-list
        position (:meth:`_compose_full`) and the implicit after-title fallback
        (presets / :meth:`_compose_minimal`) - build the selector identically,
        and a child theme can restyle the picker by overriding this one method.
        Renders nothing when there is at most one repo (no empty selector), the
        same rule used before. Keeps the widget id ``#add-repo`` and label id
        ``#add-repo-label`` unchanged so :meth:`_selected_repo` still finds it.

        Args:
            options: The ``(label, value)`` repo options from
                :meth:`repo_options`.

        Returns:
            The selector widgets to yield, or an empty list when there is at
            most one repo.
        """
        if len(options) <= 1:
            return []
        return [
            Label("Repository:", id="add-repo-label"),
            self.select_class(
                options,
                value=self.default_repo_value(),
                allow_blank=False,
                id="add-repo",
            ),
        ]

    def _compose_full(self) -> ComposeResult:
        """Render the multi-field layout in configured order.

        Each field is rendered by the per-kind builder selected from
        :attr:`FIELD_KINDS`. The repository selector's position depends on the
        resolved field list: if ``repo`` (:data:`~doxtr_doto.cli.tui.add_fields.REPO_FIELD`)
        is listed, the selector renders at that exact position via
        :meth:`_build_repo_selector`; otherwise (presets or a list without
        ``repo``) it is injected right after the title, preserving the historical
        placement. Either way nothing is rendered when there is at most one repo.
        """
        from doxtr_doto.cli.tui import add_fields

        fields = self.build_fields()
        names = self.resolve_fields()
        options = self.repo_options()
        repo_is_positioned = add_fields.REPO_FIELD in names
        with Vertical(id="add-modal"):
            with VerticalScroll(id="add-body-scroll"):
                yield Label("New task", id="add-heading")
                for name in names:
                    if name == add_fields.REPO_FIELD:
                        # Render the repo selector at its configured position.
                        yield from self._build_repo_selector(options)
                        continue
                    yield from self._build_field(name, fields)
                    if name == "title" and not repo_is_positioned:
                        # No explicit ``repo`` entry: keep the historical
                        # after-title placement.
                        yield from self._build_repo_selector(options)
            with Horizontal(id="add-bottom"):
                yield Button("Save", id="add-save", variant="primary")

    def _build_field(self, name: str, fields: dict[str, str]) -> list[Widget]:
        """Build the label + widget(s) for one field (data-driven dispatch).

        The field's render kind comes from :attr:`FIELD_KINDS` (defaulting to
        :attr:`_DEFAULT_KIND`). The kind is mapped to a builder method name via
        the :attr:`FIELD_KIND_BUILDERS` table and that builder is invoked with
        ``(name, label, fields)``. This data-driven dispatch (no ``if``/``elif``
        chain) is the seam a child theme extends: adding a new render kind is a
        one-method + one-:attr:`FIELD_KIND_BUILDERS`-entry change.

        Args:
            name: The field name to render.
            fields: The resolved field values from :meth:`build_fields`.

        Returns:
            The ordered list of widgets to yield for this field.
        """
        kind = self.FIELD_KINDS.get(name, self._DEFAULT_KIND)
        builder_name = self.FIELD_KIND_BUILDERS.get(
            kind, self.FIELD_KIND_BUILDERS[self._DEFAULT_KIND]
        )
        builder = getattr(self, builder_name)
        label = self.FIELD_LABELS.get(
            name, BY_NAME[name].display_label if name in BY_NAME else name.title()
        )
        result: list[Widget] = builder(name, label, fields)
        return result

    def _build_input(self, name: str, label: str, fields: dict[str, str]) -> list[Widget]:
        """Build a labelled single-line input for a text/date/duration field.

        The ``input`` kind (and the ``date`` / ``duration`` / ``depends`` /
        ``tags`` kinds, which render as a plain input today) all route here.
        Its suggester comes from the :meth:`field_suggester` dispatch seam, so
        a theme can wire a suggester for a new field without overriding this
        builder.

        Args:
            name: The field name.
            label: The field label.
            fields: The resolved field values from :meth:`build_fields`.

        Returns:
            The label + input widgets.
        """
        return [
            Label(label),
            self.input_class(
                value=fields.get(name, ""),
                id=f"add-{name}",
                suggester=self.field_suggester(name),
            ),
        ]

    def _build_textarea(self, name: str, label: str, fields: dict[str, str]) -> list[Widget]:
        """Build a labelled multi-line text area for the ``textarea`` kind.

        Args:
            name: The field name (e.g. ``body``).
            label: The field label.
            fields: The resolved field values from :meth:`build_fields`.

        Returns:
            The label + text-area widgets.
        """
        return [
            Label(label),
            self.text_area_class(
                text=fields.get(name, ""),
                soft_wrap=True,
                id=f"add-{name}",
            ),
        ]

    def _build_raci(self, name: str, label: str, fields: dict[str, str]) -> list[Widget]:
        """Build the RACI role sub-inputs for the ``raci`` kind.

        A thin :attr:`FIELD_KIND_BUILDERS` adapter delegating to
        :meth:`build_raci_inputs` (the overridable RACI seam). ``name`` /
        ``label`` are unused because the RACI region supplies its own role
        labels.

        Args:
            name: The field name (``raci``); unused.
            label: The field label; unused (per-role labels are used instead).
            fields: The resolved field values from :meth:`build_fields`.

        Returns:
            The RACI role label/input widgets.
        """
        return self.build_raci_inputs(fields)

    def _build_select_field(self, name: str, label: str, fields: dict[str, str]) -> list[Widget]:
        """Build a labelled priority/status select pre-selected to its default.

        The choice list comes from the :meth:`select_choices` seam. An initial
        value that is not a valid choice falls back to
        :data:`textual.widgets.Select.BLANK`.

        Args:
            name: The field name (``priority`` or ``status``).
            label: The field label.
            fields: The resolved field values from :meth:`build_fields`.

        Returns:
            The label + select widgets.
        """
        choices = self.select_choices(name)
        default = fields.get(name, "")
        # Passing ``Select.BLANK`` explicitly as ``value=`` is rejected by
        # Textual's validator, so only pass a real selection; an invalid/empty
        # default lets the select default to blank (allow_blank=True).
        value_kwargs: dict[str, Any] = {"value": default} if default in choices else {}
        return [
            Label(label),
            self.select_class(
                [(c, c) for c in choices],
                allow_blank=True,
                id=f"add-{name}",
                **value_kwargs,
            ),
        ]

    def _selected_repo(self) -> DiscoveredRepo:
        """Return the repository chosen in the selector (or the current repo).

        When the selector is absent (single-repo setups) or blank, the current
        repo is used so a task is always created somewhere sensible.
        """
        try:
            select = self.query_one("#add-repo", Select)
        except NoMatches:
            return self.current
        value = select.value
        if value is Select.BLANK or not isinstance(value, str):
            return self.current
        return self.repo_for_value(value)

    @staticmethod
    def parse_progress(raw: str) -> int | None:
        """Parse the progress input into a 0-100 integer percentage.

        ``progress`` is typed as ``int | None`` end to end (see
        :class:`doxtr_doto.collectors.DotoTask`,
        :class:`doxtr_doto.sync.json_store.TaskData`) and is interpreted as a
        0-100 percent-complete value - the same range the ``:progress:``
        directive option validates
        (:meth:`doxtr_doto.directives.doto.DotoDirective._get_progress`) and the
        HTML template renders as a percent bar
        (:func:`doxtr_doto.template_loader`). An empty/whitespace input returns
        None; a non-integer or out-of-range value raises :class:`ValueError`
        with a user-friendly message so :meth:`_submit` keeps the modal open
        rather than storing a value that would crash at render time (mirroring
        :meth:`parse_due` / :meth:`parse_estimate`).

        Args:
            raw: The raw progress input string.

        Returns:
            The progress percentage (0-100), or None to leave it unset.

        Raises:
            ValueError: If the input is non-empty and not an integer in 0-100.
        """
        value = raw.strip()
        if not value:
            return None
        try:
            progress = int(value)
        except ValueError as err:
            raise ValueError(f"Invalid progress '{value}': must be a whole number 0-100.") from err
        if not 0 <= progress <= 100:
            raise ValueError(f"Progress must be between 0 and 100, got {progress}.")
        return progress

    def collect_result(self) -> AddTaskResult | None:
        """Collect the modal's widget values into an :class:`AddTaskResult`.

        Iterates :meth:`resolve_fields` (the exact fields this modal rendered)
        and reads each field's widget value generically, dispatching on its
        :attr:`FIELD_KINDS` kind: ``select`` reads the dropdown, ``textarea``
        reads the body text, ``raci`` assembles the role inputs, and every
        other (input-like) kind reads the text input, with the ``due`` /
        ``estimate`` / ``progress`` values parsed via :meth:`parse_due` /
        :meth:`parse_estimate` / :meth:`parse_progress` so an invalid value
        raises :class:`ValueError` here rather than writing a corrupt task.
        Absent fields keep their :class:`AddTaskResult` default of None.

        The collected values are mapped onto the fixed :class:`AddTaskResult`
        fields. A newly registered field that is not representable in
        :class:`AddTaskResult` renders but is intentionally not persisted - see
        the "Registering a new field" note in the class docstring for the exact
        touch-points needed to carry a new field through the create pipeline.

        The title is required: an empty title returns None (cancel). Tags /
        depends_on are kept as their raw comma-separated strings
        (``_build_task_data`` splits them, matching ``doto add``).

        Returns:
            The assembled result, or None when the title is empty.

        Raises:
            ValueError: If a due-date, estimate or progress input is non-empty
                and invalid (surfaced to the user; the modal stays open).
        """
        from doxtr_doto.cli.tui import add_fields

        names = self.resolve_fields()
        collected: dict[str, Any] = {}
        for name in names:
            if name == add_fields.REPO_FIELD:
                # ``repo`` is the selector pseudo-field, not a value field: it
                # is collected separately via ``_selected_repo()`` below. Skip
                # it here so it is not read as a (nonexistent) text input.
                continue
            kind = self.FIELD_KINDS.get(name, self._DEFAULT_KIND)
            if kind == "raci":
                collected["raci"] = self._collect_raci_string()
            elif kind == "select":
                collected[name] = self._field_select(name)
            elif kind == "textarea":
                collected[name] = self._field_body(name) or None
            elif name == "due":
                collected["due"] = self.parse_due(self._field_text(name))
            elif name == "estimate":
                collected["estimate"] = self.parse_estimate(self._field_text(name))
            elif name == "progress":
                collected["progress"] = self.parse_progress(self._field_text(name))
            else:
                collected[name] = self._field_text(name).strip() or None

        title = (collected.get("title") or "").strip()
        if not title:
            return None

        # Map the generically-collected values onto the fixed result fields.
        # Unknown/unrepresentable field names are dropped here (they render but
        # are not persisted; see the class docstring's new-field caveat).
        known = set(AddTaskResult._fields)
        kwargs = {k: v for k, v in collected.items() if k in known and k not in ("title",)}
        return AddTaskResult(
            title=title,
            repo=self._selected_repo(),
            **kwargs,
        )

    def _field_text(self, name: str) -> str:
        """Return the text value of a single-line input field, or "" if absent."""
        try:
            return self.query_one(f"#add-{name}", Input).value
        except NoMatches:
            # The minimal layout uses the historical ``#add-input`` id for title.
            if name == "title":
                try:
                    return self.query_one("#add-input", Input).value
                except NoMatches:
                    return ""
            return ""

    def _field_body(self, name: str) -> str:
        """Return the text of a body text-area field, or "" if absent."""
        try:
            return self.query_one(f"#add-{name}", TextArea).text
        except NoMatches:
            return ""

    def _field_select(self, name: str) -> str | None:
        """Return a select field's value, or None when absent/blank."""
        try:
            select = self.query_one(f"#add-{name}", Select)
        except NoMatches:
            return None
        value = select.value
        if value is Select.BLANK or not isinstance(value, str):
            return None
        return value

    def _collect_raci_string(self) -> str | None:
        """Assemble the RACI role inputs into a ``"role names, ..."`` string.

        Each role's comma-separated input is parsed via
        :func:`doxtr_doto.raci.split_names` and rendered back as
        ``"<role> name1, name2"`` segments joined with ``", "`` so
        ``_build_task_data``'s :func:`doxtr_doto.raci.parse_raci` reparses it.
        Returns None when the RACI field is absent or every role is empty (so
        ``_build_task_data`` applies its current-user default).

        Returns:
            The RACI directive string, or None.
        """
        from doxtr_doto.raci import split_names

        segments: list[str] = []
        for role, _label, widget_id in self.RACI_FIELDS:
            try:
                raw = self.query_one(f"#{widget_id}", Input).value
            except NoMatches:
                return None
            names = split_names(raw)
            if names:
                segments.append(f"{role} {', '.join(names)}")
        return ", ".join(segments) if segments else None

    def _submit(self) -> None:
        """Collect the result and dismiss (or stay open on an invalid value).

        Mirrors :meth:`EditTaskScreen._submit`: a :class:`ValueError` from
        :meth:`collect_result` (bad due/estimate) surfaces a notification and
        keeps the modal open rather than writing a corrupt task. An empty title
        dismisses with None (cancel).
        """
        try:
            result = self.collect_result()
        except ValueError as exc:
            self.notify(str(exc), title="Invalid field value", severity="error")
            return
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit when the Save button is pressed (multi-field layout)."""
        if event.button.id == "add-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit on Enter in a single-line input.

        In the minimal (title-only) layout this preserves the original
        behavior: an empty title dismisses with None, otherwise the task is
        created. In a multi-field layout Enter in any input also submits (the
        body text area does not fire this event, so Enter there inserts a
        newline), mirroring :meth:`EditTaskScreen.on_input_submitted`.
        """
        self._submit()

    def action_cancel(self) -> None:
        """Dismiss the modal without creating a task."""
        self.dismiss(None)


class AddSeriesResult(NamedTuple):
    """The outcome of the add-series modal.

    Dismissed by :class:`AddSeriesScreen` when the user submits a valid form;
    an invalid form keeps the modal open (errors surfaced via a notification)
    and ``Escape`` cancels and dismisses ``None`` instead, so a non-``None``
    result always carries a usable, already-validated series spec.

    The validated fields come from
    :func:`doxtr_doto.cli.tui.add_series_fields.validate_series_form`; they are
    forwarded by :meth:`DotoApp.action_add_series` to
    :func:`doxtr_doto.cli.tui.actions.add_series` (the SAME reusable series
    builder the CLI ``doto add --repeat`` path uses).

    Attributes:
        title: The series title template (stripped, never empty).
        pattern_str: The full pattern string (base pattern + any ``at`` /
            ``for`` suffix), ready for
            :func:`doxtr_doto.cli.recurrence.parse_recurrence`.
        from_date: The resolved series start date.
        until_date: The resolved series end date.
        repo: The repository the series should be created in (the current repo
            by default, or whichever the user picked in the selector).
    """

    title: str
    pattern_str: str
    from_date: date
    until_date: date
    repo: DiscoveredRepo


class AddSeriesScreen(ModalScreen["AddSeriesResult | None"]):
    """Modal prompting for a new recurring *series* and its target repository.

    Dismisses with an :class:`AddSeriesResult` carrying the validated series
    spec and the chosen repository, or ``None`` if cancelled (``Escape``). The
    actual series creation is performed by the app via
    :func:`doxtr_doto.cli.tui.actions.add_series` -- the SAME reusable builder
    the CLI ``doto add --repeat`` path uses -- so the TUI never duplicates the
    occurrence/series-building code.

    **Fields.** The dialog collects a free-text recurrence *pattern* (e.g.
    ``every 2 weeks on monday``) plus dedicated *start time* (``at``) and
    *duration* (``for``) inputs, a *from* date (optional, defaults to today), a
    required *until* date, and a repository selector (when >1 repo, like
    :class:`AddTaskScreen`). The title supports ``{date}`` templating like the
    CLI. All data/validation logic lives in the terminal-free
    :mod:`doxtr_doto.cli.tui.add_series_fields` helper
    (:func:`~doxtr_doto.cli.tui.add_series_fields.validate_series_form`), so it
    is unit-tested without a live terminal; the screen is a thin view over it.

    **Overridability (child themes).** The whole screen is swappable via
    :attr:`DotoApp.add_series_screen_class` (mirroring
    :attr:`DotoApp.add_task_screen_class`). The single-line input class
    (:attr:`input_class`) and the repo selector class (:attr:`select_class`)
    are overridable so a theme can restyle the fields without reimplementing
    :meth:`compose`. The ``(label, value)`` repo option list is built by the
    pure, render-independent :func:`build_repo_options` helper (shared with
    :class:`AddTaskScreen`).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: Overridable single-line input class for the text fields. Defaults to
    #: :class:`KillRingInput` (bash-style kill/yank), mirroring
    #: :class:`AddTaskScreen`.
    input_class: type[Input] = KillRingInput

    #: Overridable select widget class for the repo picker. Defaults to
    #: :class:`FilterableSelect` (type-to-filter), mirroring
    #: :class:`AddTaskScreen`.
    select_class: type[Select[str]] = FilterableSelect

    def __init__(
        self,
        repos: list[DiscoveredRepo],
        current: DiscoveredRepo,
        *,
        width_percent: int = 75,
    ) -> None:
        """Initialize the add-series modal.

        Args:
            repos: The cached repositories (from
                :func:`doxtr_doto.cli.tui.data.list_repos`) offered in the repo
                selector.
            current: The current working directory's repository (from
                :func:`doxtr_doto.cli.tui.data.current_repo`), used as the
                selector's default.
            width_percent: The modal's width as a percentage of the terminal
                width (applied in :meth:`on_mount`). Defaults to ``75`` so the
                screen can be constructed directly in tests.
        """
        super().__init__()
        self.repos = repos
        self.current = current
        self.width_percent = width_percent

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS)."""
        _apply_modal_width(
            self.query_one("#add-series-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the configurable width when the terminal is resized."""
        _apply_modal_width(
            self.query_one("#add-series-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def repo_options(self) -> list[tuple[str, str]]:
        """Return the ``(label, value)`` options for the repo selector.

        Delegates to the pure :func:`build_repo_options` helper so the current
        repo is listed first (and defaulted), mirroring
        :meth:`AddTaskScreen.repo_options`.
        """
        return build_repo_options(self.repos, self.current)

    def repo_for_value(self, value: str) -> DiscoveredRepo:
        """Resolve a selected option value (a repo path) to its repository.

        Falls back to the current repo when the value does not match a known
        repository (e.g. the selector is blank), so the result is always
        usable. Mirrors :meth:`AddTaskScreen.repo_for_value`.
        """
        if value == self.current.path:
            return self.current
        for repo in self.repos:
            if repo.path == value:
                return repo
        return self.current

    def compose(self) -> ComposeResult:
        """Build the modal's widgets (fields in a scroll + a docked Save).

        Mirrors :meth:`EditTaskScreen.compose`: the fields live in a scrolling
        region (``#add-series-body``) and the ``Save`` button is docked at the
        bottom (``#add-series-bottom``). The repo selector renders only when
        more than one repo is available (same rule as
        :class:`AddTaskScreen`).
        """
        options = self.repo_options()
        with Vertical(id="add-series-modal"):
            with VerticalScroll(id="add-series-body"):
                yield Label("New recurring series", id="add-series-heading")
                yield Label("Title (supports {date})")
                yield self.input_class(placeholder="Series title", id="add-series-title")
                yield Label("Repeat pattern (e.g. every 2 weeks on monday)")
                yield self.input_class(placeholder="every friday", id="add-series-pattern")
                yield Label("Start time (optional, e.g. 16:00)")
                yield self.input_class(placeholder="16:00", id="add-series-time")
                yield Label("Duration (optional, e.g. 2h, 90m, 1h30m)")
                yield self.input_class(placeholder="2h", id="add-series-duration")
                yield Label("From date (optional, default today)")
                yield self.input_class(placeholder="today", id="add-series-from")
                yield Label("Until date (required, e.g. 2027-10-10 or +6m)")
                yield self.input_class(placeholder="+6m", id="add-series-until")
                if len(options) > 1:
                    yield Label("Repository:", id="add-series-repo-label")
                    yield self.select_class(
                        options,
                        value=self.current.path,
                        allow_blank=False,
                        id="add-series-repo",
                    )
            with Horizontal(id="add-series-bottom"):
                yield Button("Save", id="add-series-save", variant="primary")

    def _field_text(self, widget_id: str) -> str:
        """Return a single-line input's value, or "" when the field is absent."""
        try:
            return self.query_one(f"#{widget_id}", Input).value
        except NoMatches:
            return ""

    def form_values(self) -> SeriesFormValues:
        """Read the raw field values into a terminal-free form-values tuple.

        The returned :class:`~doxtr_doto.cli.tui.add_series_fields.SeriesFormValues`
        is validated by
        :func:`doxtr_doto.cli.tui.add_series_fields.validate_series_form` (which
        has no terminal dependency), keeping the screen a thin view over the
        pure helper.
        """
        from doxtr_doto.cli.tui.add_series_fields import SeriesFormValues

        return SeriesFormValues(
            title=self._field_text("add-series-title"),
            pattern=self._field_text("add-series-pattern"),
            start_time=self._field_text("add-series-time"),
            duration=self._field_text("add-series-duration"),
            from_date=self._field_text("add-series-from"),
            until_date=self._field_text("add-series-until"),
        )

    def _selected_repo(self) -> DiscoveredRepo:
        """Return the repository chosen in the selector (or the current repo).

        When the selector is absent (single-repo setups) or blank, the current
        repo is used so a series is always created somewhere sensible.
        """
        try:
            select = self.query_one("#add-series-repo", Select)
        except NoMatches:
            return self.current
        value = select.value
        if value is Select.BLANK or not isinstance(value, str):
            return self.current
        return self.repo_for_value(value)

    def collect_result(self) -> AddSeriesResult | None:
        """Validate the form and build an :class:`AddSeriesResult`.

        Delegates validation to the pure
        :func:`doxtr_doto.cli.tui.add_series_fields.validate_series_form`. On
        success returns the assembled result (with the chosen repo); on failure
        raises :class:`ValueError` whose message lists every field error, so
        :meth:`_submit` surfaces them and keeps the modal open.

        Returns:
            The validated :class:`AddSeriesResult`.

        Raises:
            ValueError: If the form has one or more validation errors.
        """
        from doxtr_doto.cli.tui.add_series_fields import validate_series_form

        result, errors = validate_series_form(self.form_values())
        if errors:
            raise ValueError("\n".join(errors))
        assert result is not None
        return AddSeriesResult(
            title=result.title,
            pattern_str=result.pattern_str,
            from_date=result.from_date,
            until_date=result.until_date,
            repo=self._selected_repo(),
        )

    def _submit(self) -> None:
        """Collect the result and dismiss (or stay open on an invalid form).

        Mirrors :meth:`AddTaskScreen._submit`: a :class:`ValueError` from
        :meth:`collect_result` surfaces a notification listing the field
        errors and keeps the modal open rather than creating a bad series.
        """
        try:
            result = self.collect_result()
        except ValueError as exc:
            self.notify(str(exc), title="Invalid series", severity="error")
            return
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit when the Save button is pressed."""
        if event.button.id == "add-series-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit on Enter in any single-line input."""
        self._submit()

    def action_cancel(self) -> None:
        """Dismiss the modal without creating a series."""
        self.dismiss(None)


class EditSeriesResult(NamedTuple):
    """The outcome of the edit-series modal.

    Dismissed by :class:`EditSeriesScreen` when the user submits a valid form;
    an invalid form keeps the modal open (errors surfaced via a notification)
    and ``Escape`` cancels and dismisses ``None`` instead.

    The validated fields come from
    :func:`doxtr_doto.cli.tui.edit_series_fields.validate_edit_series_form`;
    they are forwarded by :meth:`DotoApp.action_edit_series` to
    :func:`doxtr_doto.cli.tui.actions.update_series` (the SAME reusable
    series-update function the CLI ``doto series update`` path uses).

    Attributes:
        series_id: The id of the series being edited.
        pattern_str: The composed pattern string (base pattern + any ``at`` /
            ``for`` suffix), ready for
            :func:`doxtr_doto.cli.recurrence.parse_recurrence`, or ``None`` when
            the pattern field was left blank (keep the stored calendar shape).
        title: The new title template, or ``None`` when the title field was
            left blank (keep the stored title).
        start_time: The parsed start time, or ``None`` when the start-time
            field was blank (CLEAR the per-occurrence start time).
        duration_minutes: The parsed duration in whole minutes, or ``None``
            when the duration field was blank (CLEAR the per-occurrence
            duration).
    """

    series_id: str
    pattern_str: str | None
    title: str | None
    start_time: time | None
    duration_minutes: int | None


class EditSeriesScreen(ModalScreen["EditSeriesResult | None"]):
    """Modal for editing an existing *series* from a selected occurrence forward.

    Dismisses with an :class:`EditSeriesResult` carrying the validated edit, or
    ``None`` if cancelled (``Escape``). The actual series update (the
    forward-only re-stamp) is performed by the app via
    :func:`doxtr_doto.cli.tui.actions.update_series` -- the SAME reusable
    function the CLI ``doto series update`` path uses -- so the TUI never
    duplicates the update logic.

    **Fields.** The dialog pre-populates the title, base pattern (no ``at`` /
    ``for`` suffix, via :func:`doxtr_doto.cli.recurrence.pattern_base_str`),
    start time (``HH:MM``) and duration (via
    :func:`doxtr_doto.date_utils.format_duration_minutes`) from the stored
    series. Unlike :class:`AddSeriesScreen` it has NO from/until/apply-to
    fields: the forward-only anchor comes from the selected row (captured by
    the app), shown here as a read-only context line. Blank start-time /
    duration CLEAR those fields; blank pattern / title KEEP them unchanged (see
    :mod:`doxtr_doto.cli.tui.edit_series_fields`).

    **Overridability (child themes).** The whole screen is swappable via
    :attr:`DotoApp.edit_series_screen_class` (mirroring
    :attr:`DotoApp.add_series_screen_class`). The single-line input class
    (:attr:`input_class`) is overridable so a theme can restyle the fields
    without reimplementing :meth:`compose`.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: Overridable single-line input class for the text fields. Defaults to
    #: :class:`KillRingInput`, mirroring :class:`AddSeriesScreen`.
    input_class: type[Input] = KillRingInput

    def __init__(
        self,
        series_id: str,
        series_data: dict[str, Any],
        anchor_date: date,
        forward_count: int,
        earlier_count: int,
        *,
        width_percent: int = 75,
    ) -> None:
        """Initialize the edit-series modal.

        Args:
            series_id: The id of the series being edited.
            series_data: The stored series dict (used to pre-populate fields
                and the context line).
            anchor_date: The forward-only anchor (the selected occurrence's
                due date) -- occurrences on/after it are affected.
            forward_count: The number of occurrences on/after the anchor.
            earlier_count: The number of occurrences before the anchor (left
                unchanged).
            width_percent: The modal's width as a percentage of the terminal
                width (applied in :meth:`on_mount`). Defaults to ``75`` so the
                screen can be constructed directly in tests.
        """
        super().__init__()
        self.series_id = series_id
        self.series_data = series_data
        self.anchor_date = anchor_date
        self.forward_count = forward_count
        self.earlier_count = earlier_count
        self.width_percent = width_percent

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS)."""
        _apply_modal_width(
            self.query_one("#edit-series-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the configurable width when the terminal is resized."""
        _apply_modal_width(
            self.query_one("#edit-series-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def initial_fields(self) -> dict[str, str]:
        """Return the pre-populated string values for the editable fields.

        The base pattern uses :func:`doxtr_doto.cli.recurrence.pattern_base_str`
        (so it round-trips through :func:`parse_recurrence`), the start time is
        ``HH:MM`` (empty when the series has none) and the duration is rendered
        via :func:`doxtr_doto.date_utils.format_duration_minutes` (empty when
        the series has none).

        Returns:
            A mapping of field id suffix to its pre-populated string value.
        """
        from doxtr_doto.cli.recurrence import RecurrencePattern, format_time, pattern_base_str
        from doxtr_doto.date_utils import format_duration_minutes

        pattern = RecurrencePattern.from_dict(self.series_data["pattern"])
        start_time = format_time(pattern.start_time) or ""
        duration = (
            format_duration_minutes(pattern.duration_minutes)
            if pattern.duration_minutes is not None
            else ""
        )
        return {
            "title": str(self.series_data.get("title_template") or ""),
            "pattern": pattern_base_str(pattern),
            "time": start_time,
            "duration": duration,
        }

    def context_line(self) -> str:
        """Return the read-only context line shown above the fields.

        Names the series id, its current pattern description and the
        forward-only anchor with the affected / unchanged occurrence counts, so
        the user knows exactly what the edit will re-stamp.
        """
        from doxtr_doto.cli.recurrence import RecurrencePattern

        pattern = RecurrencePattern.from_dict(self.series_data["pattern"])
        return (
            f"{self.series_id}  ({pattern.describe()})\n"
            f"Applies to {self.anchor_date.isoformat()} and later "
            f"({self.forward_count} occurrences); "
            f"{self.earlier_count} earlier occurrences unchanged."
        )

    def compose(self) -> ComposeResult:
        """Build the modal's widgets (fields in a scroll + a docked Save).

        Mirrors :meth:`AddSeriesScreen.compose`: the fields live in a scrolling
        region (``#edit-series-body``) and the ``Save`` button is docked at the
        bottom (``#edit-series-bottom``). A read-only context line
        (``#edit-series-context``) shows the anchor + occurrence counts.
        """
        fields = self.initial_fields()
        with Vertical(id="edit-series-modal"):
            with VerticalScroll(id="edit-series-body"):
                yield Label(
                    "Edit series (from selected occurrence forward)", id="edit-series-heading"
                )
                yield Label(self.context_line(), id="edit-series-context")
                yield Label("Title (supports {date}; blank keeps current)")
                yield self.input_class(value=fields["title"], id="edit-series-title")
                yield Label("Repeat pattern (blank keeps current shape)")
                yield self.input_class(value=fields["pattern"], id="edit-series-pattern")
                yield Label("Start time (blank clears, e.g. 16:00)")
                yield self.input_class(value=fields["time"], id="edit-series-time")
                yield Label("Duration (blank clears, e.g. 2h, 90m)")
                yield self.input_class(value=fields["duration"], id="edit-series-duration")
            with Horizontal(id="edit-series-bottom"):
                yield Button("Save", id="edit-series-save", variant="primary")

    def _field_text(self, widget_id: str) -> str:
        """Return a single-line input's value, or "" when the field is absent."""
        try:
            return self.query_one(f"#{widget_id}", Input).value
        except NoMatches:
            return ""

    def form_values(self) -> EditSeriesFormValues:
        """Read the raw field values into a terminal-free form-values tuple.

        The returned
        :class:`~doxtr_doto.cli.tui.edit_series_fields.EditSeriesFormValues` is
        validated by
        :func:`doxtr_doto.cli.tui.edit_series_fields.validate_edit_series_form`
        (which has no terminal dependency), keeping the screen a thin view.
        """
        from doxtr_doto.cli.tui.edit_series_fields import EditSeriesFormValues

        return EditSeriesFormValues(
            title=self._field_text("edit-series-title"),
            pattern=self._field_text("edit-series-pattern"),
            start_time=self._field_text("edit-series-time"),
            duration=self._field_text("edit-series-duration"),
        )

    def collect_result(self) -> EditSeriesResult:
        """Validate the form and build an :class:`EditSeriesResult`.

        Delegates validation to the pure
        :func:`doxtr_doto.cli.tui.edit_series_fields.validate_edit_series_form`.
        On success returns the assembled result; on failure raises
        :class:`ValueError` whose message lists every field error, so
        :meth:`_submit` surfaces them and keeps the modal open.

        Returns:
            The validated :class:`EditSeriesResult`.

        Raises:
            ValueError: If the form has one or more validation errors.
        """
        from doxtr_doto.cli.tui.edit_series_fields import validate_edit_series_form

        result, errors = validate_edit_series_form(self.form_values())
        if errors:
            raise ValueError("\n".join(errors))
        assert result is not None
        return EditSeriesResult(
            series_id=self.series_id,
            pattern_str=result.pattern_str,
            title=result.title,
            start_time=result.start_time,
            duration_minutes=result.duration_minutes,
        )

    def _submit(self) -> None:
        """Collect the result and dismiss (or stay open on an invalid form).

        Mirrors :meth:`AddSeriesScreen._submit`: a :class:`ValueError` from
        :meth:`collect_result` surfaces a notification listing the field errors
        and keeps the modal open rather than applying a bad edit.
        """
        try:
            result = self.collect_result()
        except ValueError as exc:
            self.notify(str(exc), title="Invalid series edit", severity="error")
            return
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit when the Save button is pressed."""
        if event.button.id == "edit-series-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit on Enter in any single-line input."""
        self._submit()

    def action_cancel(self) -> None:
        """Dismiss the modal without editing the series."""
        self.dismiss(None)


class ConfirmResult(str, Enum):
    """The outcome of a :class:`ConfirmScreen`.

    A string enum so a plain yes/no confirm can compare against
    :attr:`CONFIRM` and a three-way series-delete confirm can distinguish
    :attr:`CONFIRM` (delete series + tasks), :attr:`KEEP_TASKS` (remove the
    series but keep its tasks) and :attr:`CANCEL`.
    """

    CONFIRM = "confirm"
    KEEP_TASKS = "keep_tasks"
    CANCEL = "cancel"


class ConfirmScreen(ModalScreen["ConfirmResult"]):
    """A generic yes/no (or three-way) confirmation modal.

    Dismisses with a :class:`ConfirmResult`. ``Escape`` cancels
    (:attr:`ConfirmResult.CANCEL`). For a plain confirm only a ``Confirm`` /
    ``Cancel`` pair is shown and the result is :attr:`~ConfirmResult.CONFIRM`
    or :attr:`~ConfirmResult.CANCEL`. When ``keep_tasks_label`` is given a
    third button offers :attr:`~ConfirmResult.KEEP_TASKS` (parity with the CLI
    ``series delete --keep-tasks``), so the series-delete flow can offer
    "Delete series + tasks" / "Keep tasks, remove series" / Cancel.

    Overridable via :attr:`DotoApp.confirm_screen_class` (mirroring the other
    modal seams).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        message: str,
        *,
        confirm_label: str = "Confirm",
        keep_tasks_label: str | None = None,
        cancel_label: str = "Cancel",
        width_percent: int = 75,
    ) -> None:
        """Initialize the confirmation modal.

        Args:
            message: The prompt message shown to the user.
            confirm_label: The label for the primary confirm button.
            keep_tasks_label: When given, adds a third "keep tasks" button
                (series-delete flow); when None the modal is a plain yes/no.
            cancel_label: The label for the cancel button.
            width_percent: The modal's width as a percentage of the terminal
                width. Defaults to ``75`` so the screen can be constructed
                directly in tests.
        """
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.keep_tasks_label = keep_tasks_label
        self.cancel_label = cancel_label
        self.width_percent = width_percent

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS)."""
        _apply_modal_width(
            self.query_one("#confirm-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def compose(self) -> ComposeResult:
        """Build the prompt label and the confirm/(keep)/cancel buttons."""
        with Vertical(id="confirm-modal"):
            yield Label(self.message, id="confirm-message")
            with Horizontal(id="confirm-bottom"):
                yield Button(self.confirm_label, id="confirm-yes", variant="error")
                if self.keep_tasks_label is not None:
                    yield Button(self.keep_tasks_label, id="confirm-keep", variant="primary")
                yield Button(self.cancel_label, id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss with the result matching the pressed button."""
        if event.button.id == "confirm-yes":
            self.dismiss(ConfirmResult.CONFIRM)
        elif event.button.id == "confirm-keep":
            self.dismiss(ConfirmResult.KEEP_TASKS)
        else:
            self.dismiss(ConfirmResult.CANCEL)

    def action_cancel(self) -> None:
        """Dismiss the modal as cancelled."""
        self.dismiss(ConfirmResult.CANCEL)


class ConflictResolveScreen(ModalScreen["str | None"]):
    """Modal to resolve a task's calendar-sync conflict (keep local/remote/both).

    Shows each field that diverged on both sides with a short preview of the
    local and remote values, then offers three one-press choices:

    * **Local** -- keep the local value, discard the remote edit.
    * **Remote** -- take the calendar value, discard the local edit.
    * **Both** -- keep both (the diff3-merged body with markers / joined
      scalar), so nothing is lost and the user trims it in the editor.

    Dismisses with the chosen :class:`doxtr_doto.calsync.resolve.ResolutionChoice`
    *value* (``"local"`` / ``"remote"`` / ``"both"``), or ``None`` on cancel so
    the caller leaves the conflict untouched. The modal only renders the choice;
    applying it (and clearing the flag) is the caller's job via the shared
    :func:`doxtr_doto.calsync.resolve.resolve_conflict` helper, so the TUI and
    the ``doto calsync resolve`` CLI can never diverge.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("l", "local", "Keep local"),
        ("r", "remote", "Keep remote"),
        ("b", "both", "Keep both"),
    ]

    def __init__(
        self,
        task_id: str,
        conflicts: list[dict[str, str]],
        *,
        width_percent: int = 75,
    ) -> None:
        """Initialize the resolver from a task's conflict records.

        Args:
            task_id: The conflicted task id (for the title).
            conflicts: The per-field records (``field``/``local``/``remote``/
                ``both``) from ``task["_sync"]["conflict"]["fields"]``.
            width_percent: Modal width as a percent of terminal width.
        """
        super().__init__()
        self.task_id = task_id
        self.conflicts = conflicts
        self.width_percent = width_percent

    @staticmethod
    def _preview(value: str, width: int = 60) -> str:
        """One-line, width-capped preview of a (possibly multi-line) value."""
        one_line = " ".join(str(value).split())
        if len(one_line) > width:
            return one_line[: width - 1] + "\u2026"
        return one_line or "(empty)"

    def compose(self) -> ComposeResult:
        """Build the per-field preview and the local/remote/both/cancel buttons."""
        with Vertical(id="conflict-modal"):
            yield Label(f"Resolve sync conflict - {self.task_id}", id="conflict-title")
            with VerticalScroll(id="conflict-fields"):
                for rec in self.conflicts:
                    field = str(rec.get("field", ""))
                    local_prev, remote_prev = resolve.conflict_preview(rec)
                    yield Label(f"[{field}]", classes="conflict-field-name")
                    yield Static(
                        f"  local : {escape_markup(self._preview(local_prev))}",
                        classes="conflict-local",
                    )
                    yield Static(
                        f"  remote: {escape_markup(self._preview(remote_prev))}",
                        classes="conflict-remote",
                    )
            with Horizontal(id="conflict-bottom"):
                yield Button("Keep Local (l)", id="conflict-local", variant="primary")
                yield Button("Keep Remote (r)", id="conflict-remote", variant="primary")
                yield Button("Keep Both (b)", id="conflict-both")
                yield Button("Cancel", id="conflict-cancel")

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS)."""
        _apply_modal_width(
            self.query_one("#conflict-modal", Vertical),
            self.app.size.width,
            self.width_percent,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss with the choice matching the pressed button."""
        mapping = {
            "conflict-local": "local",
            "conflict-remote": "remote",
            "conflict-both": "both",
        }
        self.dismiss(mapping.get(event.button.id or ""))

    def action_local(self) -> None:
        """Keep the local value (``l``)."""
        self.dismiss("local")

    def action_remote(self) -> None:
        """Keep the remote value (``r``)."""
        self.dismiss("remote")

    def action_both(self) -> None:
        """Keep both values (``b``)."""
        self.dismiss("both")

    def action_cancel(self) -> None:
        """Dismiss without resolving."""
        self.dismiss(None)


class EditTaskScreen(_TaskFieldWidgetsMixin, ModalScreen["dict[str, Any] | None"]):
    """Modal for editing the selected task's fields.

    Pre-populates inputs from the current task and, on submit, dismisses with
    an ``updates`` dict suitable for
    :func:`doxtr_doto.cli.tui.actions.update_task` (the single-task path of
    ``doto update``). Cancelling with ``escape`` dismisses with ``None``.

    The set of editable fields is: ``title``, ``priority``, ``status``,
    ``assignee``, ``tags`` (comma-separated), ``due`` and ``body``. Status and
    priority use :class:`FilterableSelect` (populated from the configured
    status/priority lists), which supports type-to-filter / letter-select:
    typing letters narrows or selects a matching option (word-based, so
    ``"progress"`` finds ``"in-progress"``). The ``title``, ``assignee``,
    ``tags`` and ``due`` fields use plain :class:`textual.widgets.Input`;
    ``body`` uses a scrolling, soft-wrapping :class:`textual.widgets.TextArea`
    so long bodies wrap and scroll rather than overflow. The ``due`` input is
    parsed with the same :func:`doxtr_doto.cli.commands.add.parse_relative_date`
    helper as ``doto update --due`` (via :meth:`parse_due`), so absolute and
    relative dates behave identically and an invalid date surfaces an error
    without corrupting the store. The field-building and update-collection
    logic is factored into :meth:`build_fields` and :meth:`collect_updates` so
    it can be unit-tested without rendering the modal.

    Layout: the fields and body text area live in a scrolling region while the
    ``Save`` button is docked at the bottom of the modal so it stays visible
    regardless of scroll position. ``Escape`` cancels; pressing ``Enter``
    inside the body text area inserts a newline rather than submitting, so
    submit happens via the ``Save`` button.

    The select widget is overridable via :attr:`select_class` so a child theme
    can replace the type-to-filter behavior. The widget classes
    (:attr:`select_class` / :attr:`input_class` / :attr:`text_area_class`), the
    suggester seams and the :meth:`parse_due` / :meth:`parse_estimate` parsers
    come from :class:`_TaskFieldWidgetsMixin` (shared with
    :class:`AddTaskScreen`).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        task: dict[str, Any],
        statuses: list[str],
        priorities: list[str],
        known_assignees: list[str] | None = None,
        known_tags: list[str] | None = None,
        width_percent: int = 75,
    ) -> None:
        """Initialize the edit modal.

        Args:
            task: The task dict being edited (used to pre-populate inputs).
            statuses: The configured status choices for the status select.
            priorities: The configured priority choices for the priority
                select.
            known_assignees: Candidate assignee names offered as auto-complete
                suggestions in the assignee input (from
                :func:`known_assignee_names`). Defaults to an empty list.
            known_tags: Candidate tag names offered as auto-complete
                suggestions in the tags input (from :func:`known_tag_names`).
                Defaults to an empty list.
            width_percent: The modal's width as a percentage of the terminal
                width (applied in :meth:`on_mount`), from the configurable
                ``tui_modal_width_ratio`` (see
                :func:`doxtr_doto.cli.tui.actions.modal_width_percent`).
                Defaults to ``75`` (3/4) so the screen can be constructed
                directly in tests.
        """
        super().__init__()
        self.edit_task = task
        self.statuses = statuses
        self.priorities = priorities
        self.known_assignees = known_assignees or []
        self.known_tags = known_tags or []
        self.width_percent = width_percent

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS).

        The width is computed from the live terminal width (see
        :func:`_apply_modal_width`) rather than static CSS so the modal is
        exactly :attr:`width_percent` percent of the *total* terminal width;
        the height is left untouched. :meth:`on_resize` re-applies it so the
        modal tracks a terminal resize while open.
        """
        _apply_modal_width(
            self.query_one("#edit-modal", Vertical), self.app.size.width, self.width_percent
        )

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the configurable width when the terminal is resized."""
        _apply_modal_width(
            self.query_one("#edit-modal", Vertical), self.app.size.width, self.width_percent
        )

    @classmethod
    def build_fields(
        cls,
        task: dict[str, Any],
    ) -> dict[str, str]:
        """Return the initial string values for the editable text fields.

        Args:
            task: The task dict being edited.

        Returns:
            A mapping of field name to its pre-populated string value for the
            ``title``, ``assignee``, ``tags``, ``due``, ``estimate`` and
            ``body`` inputs, plus the four RACI role fields
            (``raci_responsible``, ``raci_accountable``, ``raci_consulted``,
            ``raci_informed``) as comma-separated names.
        """
        from doxtr_doto.date_utils import format_duration_minutes

        tags = task.get("tags") or []
        raci = task.get("raci") or {}
        return {
            "title": str(task.get("title") or ""),
            "assignee": str(task.get("assignee") or ""),
            "tags": ", ".join(tags),
            "due": str(task.get("due") or ""),
            "estimate": format_duration_minutes(task.get("estimate")),
            "body": str(task.get("body") or ""),
            "raci_responsible": ", ".join(raci.get("responsible", [])),
            "raci_accountable": ", ".join(raci.get("accountable", [])),
            "raci_consulted": ", ".join(raci.get("consulted", [])),
            "raci_informed": ", ".join(raci.get("informed", [])),
        }

    def compose(self) -> ComposeResult:
        """Build the modal's widgets, pre-populated from the task.

        The fields and body text area are placed inside a scrolling region
        (``#edit-body``) while the ``Save`` button is docked at the bottom of
        the modal (``#edit-bottom``) so it is always visible.
        """
        fields = self.build_fields(self.edit_task)
        task_id = self.edit_task.get("id", "")
        with Vertical(id="edit-modal"):
            with VerticalScroll(id="edit-body"):
                yield Label(f"Edit {task_id}", id="edit-title")
                yield Label("Title")
                yield self.input_class(value=fields["title"], id="edit-title-input")
                yield Label("Priority")
                yield self.select_class(
                    [(p, p) for p in self.priorities],
                    value=self._initial_select(self.edit_task.get("priority"), self.priorities),
                    allow_blank=True,
                    id="edit-priority",
                )
                yield Label("Status")
                yield self.select_class(
                    [(s, s) for s in self.statuses],
                    value=self._initial_select(self.edit_task.get("status"), self.statuses),
                    allow_blank=True,
                    id="edit-status",
                )
                yield Label("Assignee")
                yield self.input_class(
                    value=fields["assignee"],
                    id="edit-assignee",
                    suggester=self.assignee_suggester(),
                )
                yield Label("Tags (comma-separated)")
                yield self.input_class(
                    value=fields["tags"],
                    id="edit-tags",
                    suggester=self.tags_suggester(),
                )
                yield Label("Due (YYYY-MM-DD or +7d, friday; empty clears)")
                yield self.input_class(value=fields["due"], id="edit-due")
                yield Label("Estimate (e.g. 5m, 90m, 4h, 1h30m; empty clears)")
                yield self.input_class(value=fields["estimate"], id="edit-estimate")
                yield from self.build_raci_inputs(fields)
                yield Label("Body")
                yield self.text_area_class(
                    text=fields["body"],
                    soft_wrap=True,
                    id="edit-body-input",
                )
            with Horizontal(id="edit-bottom"):
                yield Button("Save", id="edit-save", variant="primary")

    @staticmethod
    def _initial_select(value: Any, choices: list[str]) -> Any:
        """Return the initial Select value, or blank when not a valid choice.

        Args:
            value: The task's current field value.
            choices: The valid choices for the select.

        Returns:
            The value if it is a valid choice, otherwise
            :data:`textual.widgets.Select.BLANK`.
        """
        if value in choices:
            return value
        return Select.BLANK

    #: The RACI role fields rendered in the edit modal, as
    #: ``(role, label, widget_id)`` tuples. Derived from the canonical
    #: :data:`doxtr_doto.raci.RACI_ROLES` and
    #: :data:`doxtr_doto.raci.RACI_ROLE_LABELS` so adding/renaming a role is a
    #: one-place change in :mod:`doxtr_doto.raci`. Overridable so a child theme
    #: can reorder/relabel the RACI inputs.
    RACI_FIELDS: tuple[tuple[str, str, str], ...] = tuple(
        (role, f"{label} (comma-separated)", f"edit-raci-{role}")
        for role, label in RACI_ROLE_LABELS.items()
    )

    def collect_updates(self) -> dict[str, Any]:
        """Collect the edited field values into an updates dict.

        Only fields that changed from the task's current value are included,
        mirroring the single-task behavior of ``doto update``. Tags are parsed
        from the comma-separated input into a sorted list. The due date is
        parsed via :meth:`parse_due` and the estimate via
        :meth:`parse_estimate` (the same parsers as ``doto update``), so an
        invalid due date or estimate raises :class:`ValueError` here rather
        than writing a corrupt value to the store.

        Returns:
            The updates mapping to pass to
            :func:`doxtr_doto.cli.tui.actions.update_task`.

        Raises:
            ValueError: If the due-date or estimate input is non-empty and
                invalid.
        """
        updates: dict[str, Any] = {}

        title = self.query_one("#edit-title-input", Input).value.strip()
        if title and title != (self.edit_task.get("title") or ""):
            updates["title"] = title

        priority = self.query_one("#edit-priority", Select).value
        if priority is not Select.BLANK and priority != self.edit_task.get("priority"):
            updates["priority"] = priority

        status = self.query_one("#edit-status", Select).value
        if status is not Select.BLANK and status != self.edit_task.get("status"):
            updates["status"] = status

        assignee = self.query_one("#edit-assignee", Input).value.strip()
        if assignee != (self.edit_task.get("assignee") or ""):
            updates["assignee"] = assignee or None

        raw_tags = self.query_one("#edit-tags", Input).value
        new_tags = sorted({t.strip() for t in raw_tags.split(",") if t.strip()})
        if new_tags != sorted(self.edit_task.get("tags") or []):
            updates["tags"] = new_tags

        new_due = self.parse_due(self.query_one("#edit-due", Input).value)
        if new_due != (self.edit_task.get("due") or None):
            updates["due"] = new_due

        new_estimate = self.parse_estimate(self.query_one("#edit-estimate", Input).value)
        if new_estimate != (self.edit_task.get("estimate") or None):
            updates["estimate"] = new_estimate

        body = self.query_one("#edit-body-input", TextArea).text
        if body != (self.edit_task.get("body") or ""):
            updates["body"] = body

        new_raci = self.collect_raci()
        if new_raci != (self.edit_task.get("raci") or None):
            updates["raci"] = new_raci

        return updates

    def collect_raci(self) -> dict[str, list[str]] | None:
        """Collect the four RACI role inputs into a RACI dict (or None).

        Each role's comma-separated input is parsed via
        :func:`doxtr_doto.raci.split_names` (the shared split/strip/dedup
        helper) so the dedup policy is defined in one place. Only roles with
        at least one name are included. Returns None when every role is empty,
        so an edit that clears all RACI data stores ``None`` rather than an
        empty dict.

        Returns:
            The RACI dict, or None when no names are entered.
        """
        from doxtr_doto.raci import split_names

        raci: dict[str, list[str]] = {}
        for role, _label, widget_id in self.RACI_FIELDS:
            raw = self.query_one(f"#{widget_id}", Input).value
            names = split_names(raw)
            if names:
                raci[role] = names
        return raci or None

    def _submit(self) -> None:
        """Collect updates and dismiss with them (or None if nothing changed).

        If the due-date or estimate input is invalid, :meth:`collect_updates`
        raises :class:`ValueError`; the modal stays open and the error is
        surfaced via a notification so an invalid value never corrupts the
        store.
        """
        try:
            updates = self.collect_updates()
        except ValueError as exc:
            self.notify(str(exc), title="Invalid field value", severity="error")
            return
        self.dismiss(updates or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit the edit when the Save button is pressed."""
        if event.button.id == "edit-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit the edit when a text :class:`Input` is submitted (Enter).

        Only the single-line :class:`textual.widgets.Input` fields fire this
        event. The body :class:`textual.widgets.TextArea` does not, so Enter
        inside the body inserts a newline rather than submitting; submission
        there happens via the ``Save`` button.
        """
        self._submit()

    def action_cancel(self) -> None:
        """Dismiss the modal without applying any edits."""
        self.dismiss(None)


class EditBodyScreen(_TaskFieldWidgetsMixin, ModalScreen["str | None"]):
    """Focused modal for editing *only* a task's Markdown body (quick ``b``).

    Unlike :class:`EditTaskScreen` - which edits every task field - this modal
    is a single full-height :class:`~textual.widgets.TextArea` dedicated to the
    task ``body`` (the free-text notes rendered as Markdown by
    :class:`CardViewerScreen`). It is reached directly with the ``n`` quick key
    (from the board or the card viewer) so capturing a quick note never goes
    through the full multi-field edit dialog.

    On submit it dismisses with the new body *string* (``""`` is a valid value
    - it clears the body); on cancel it dismisses with ``None`` so the caller
    leaves the body untouched. The body text area reuses the mixin's
    overridable :attr:`text_area_class` (bash-style kill/yank), so the editing
    affordances match :class:`EditTaskScreen`'s body field. ``Escape`` cancels
    and ``Ctrl+S`` saves; ``Enter`` inside the text area inserts a newline
    (so multi-line notes are natural) rather than submitting.

    The modal needs none of the mixin's candidate lists (there is no
    assignee/tags input here), so :attr:`known_assignees` / :attr:`known_tags`
    are set empty and :attr:`RACI_FIELDS` is empty; they exist only to satisfy
    the shared mixin contract.
    """

    #: The mixin requires these; the body editor has no assignee/tags/RACI
    #: inputs, so they are empty.
    RACI_FIELDS: tuple[tuple[str, str, str], ...] = ()

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, task: dict[str, Any], width_percent: int = 75) -> None:
        """Initialize the body editor for a task.

        Args:
            task: The task dict whose ``body`` is edited (used for the title
                label and to pre-populate the text area).
            width_percent: The modal's width as a percentage of the terminal
                width (applied in :meth:`on_mount`), from the configurable
                ``tui_modal_width_ratio`` (see
                :func:`doxtr_doto.cli.tui.actions.modal_width_percent`).
                Defaults to ``75`` (3/4) so the screen can be constructed
                directly in tests.
        """
        super().__init__()
        self.edit_task = task
        self.width_percent = width_percent
        self.known_assignees = []
        self.known_tags = []

    def compose(self) -> ComposeResult:
        """Build the modal: a title label, the body text area, and Save.

        The text area fills the modal (``#edit-body-area`` is ``height: 1fr``)
        while the ``Save`` button is docked at the bottom (``#editbody-bottom``)
        so it stays visible; ``Ctrl+S`` saves without reaching for the mouse.
        """
        task_id = self.edit_task.get("id", "")
        body = str(self.edit_task.get("body") or "")
        with Vertical(id="editbody-modal"):
            yield Label(f"Edit body - {task_id}", id="editbody-title")
            yield self.text_area_class(
                text=body,
                soft_wrap=True,
                id="editbody-input",
            )
            with Horizontal(id="editbody-bottom"):
                yield Button("Save", id="editbody-save", variant="primary")

    def on_mount(self) -> None:
        """Apply the configurable width and focus the body text area.

        The modal width is computed from the live terminal width (see
        :func:`_apply_modal_width`) so the modal is exactly
        :attr:`width_percent` percent of the *total* terminal width; the
        height stays as defined in CSS. :meth:`on_resize` re-applies it so the
        modal tracks a terminal resize while open. The body text area is
        focused so the user can type immediately.
        """
        _apply_modal_width(
            self.query_one("#editbody-modal", Vertical), self.app.size.width, self.width_percent
        )
        self.query_one("#editbody-input", TextArea).focus()

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the configurable width when the terminal is resized."""
        _apply_modal_width(
            self.query_one("#editbody-modal", Vertical), self.app.size.width, self.width_percent
        )

    def _submit(self) -> None:
        """Dismiss with the edited body string (``""`` clears the body)."""
        body = self.query_one("#editbody-input", TextArea).text
        self.dismiss(body)

    def action_save(self) -> None:
        """Save the body via the ``Ctrl+S`` keybinding."""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Save when the ``Save`` button is pressed."""
        if event.button.id == "editbody-save":
            self._submit()

    def action_cancel(self) -> None:
        """Dismiss without changing the body."""
        self.dismiss(None)


class CardViewerScreen(ModalScreen["str | None"]):
    """Modal "card viewer" showing a task's full detail (Feature 3).

    Opened by pressing ``Enter`` on a kanban card, this popup lists the
    *complete* content of the task - the same fields as the CLI
    ``doto list -f cards`` reference output
    (:meth:`doxtr_doto.cli.output.OutputFormatter.format_task_detail`): id,
    title, assignee, priority, status, due, tags, depends_on, series, created,
    updated and the body.

    The content is split into two regions. The *field* lines (id/title header,
    assignee, priority, status, due, tags, depends_on, series, created,
    updated) carry rich/Textual *style* markup (``[bold]``, ``red bold``, ...)
    and render into a soft-wrapping :class:`~textual.widgets.Static` with id
    ``viewer-detail`` so long titles/values wrap instead of clipping. The task
    *body* may contain Markdown (headings, lists, bold/italic, code, ...) and
    renders into a :class:`~textual.widgets.Markdown` widget with id
    ``viewer-md`` so the markup is displayed properly and the prose wraps
    naturally. Both live in a scrolling region
    (:class:`~textual.containers.VerticalScroll` with id ``viewer-body``) that
    is ``height: 1fr`` so it fills the modal down to the docked hint line and a
    long body scrolls rather than overflowing. If the task has no body (the
    field is absent or empty) no Markdown region is added.

    Pressing ``Enter`` again or ``Escape`` closes the viewer (dismisses with
    None). Pressing ``e`` closes the viewer and asks the app to open the
    existing :class:`EditTaskScreen` for the same task (Feature 4): the screen
    dismisses with the sentinel ``"edit"`` and the close-callback registered by
    :meth:`DotoApp._open_card_viewer` interprets it, opening the edit dialog
    via :meth:`DotoApp._open_edit`, so the edit flow (and its
    :func:`doxtr_doto.cli.tui.actions.update_task` write) is reused rather than
    duplicated.

    The detail-line assembly is factored into the pure classmethod
    :meth:`build_detail_lines` so it can be unit-tested without rendering the
    modal, mirroring :meth:`EditTaskScreen.build_fields`. A child theme can
    override the rendering at several seams:

    * :attr:`DotoApp.card_viewer_screen_class` swaps the whole screen
      (mirroring :attr:`DotoApp.edit_task_screen_class`).
    * :meth:`build_detail_lines` re-shapes the *combined* field+body lines
      (kept as the single source matching the CLI card builder
      :func:`doxtr_doto.cli.output.build_task_detail_lines`).
    * :meth:`build_field_lines` re-shapes only the field (style-markup) lines
      that render into ``#viewer-detail``.
    * :meth:`build_body_markdown` re-shapes the raw Markdown source fed to the
      body widget (returns ``None`` when there is no body).
    * :attr:`markdown_class` swaps the Markdown widget subclass used to render
      the body (defaults to :class:`~textual.widgets.Markdown`).
    * :meth:`build_body_widget` builds the body widget itself, for a theme that
      wants to replace the Markdown rendering entirely.
    * :meth:`build_extra_field_lines` assembles the popup-only extra fields
      (RACI differing from the default user + time spent) rendered into
      ``#viewer-detail`` after the shared field lines.
    * :meth:`build_raci_differing_lines` / :meth:`build_time_spent_lines` are
      the per-field sub-seams it concatenates, so a child theme can override,
      reorder, or drop one extra field without reimplementing the others.

    Two popup-only fields are appended below the shared CLI field lines (they
    are *not* part of :func:`doxtr_doto.cli.output.build_task_detail_lines`, so
    they appear only in this viewer and never in the ``doto list -f cards``
    reference card):

    * **RACI (differing from the default user).** The task's RACI roles are
      shown, but a role assigned *only* to the configured default user
      (:attr:`default_user`, from ``config.user`` falling back to
      ``config.default_assignee``) is the boring default and is suppressed;
      only the roles/names that differ are rendered (grouped by role with the
      :data:`doxtr_doto.raci.RACI_ROLE_LABELS` labels). The comparison and
      line rendering live in the overridable
      :func:`doxtr_doto.raci.render_raci_differing_lines`
      (filter: :func:`doxtr_doto.raci.filter_raci_differing`).
    * **Time spent.** How long work has been clocked on the task, summed from
      its ``worklogs`` via
      :func:`doxtr_doto.time_tracking.elapsed_seconds` and formatted by
      :func:`doxtr_doto.cli.session.format_duration`. An open (running)
      session counts up to "now", so the value reflects a live session. The
      line is omitted when no time has been tracked (see the overridable
      :func:`doxtr_doto.cli.session.render_time_spent_line`).

    These two are assembled by the overridable instance method
    :meth:`build_extra_field_lines` and rendered into ``#viewer-detail`` right
    after the shared field lines, so a child theme can re-shape or drop them
    without touching the shared CLI builder.

    Markdown *header* styling in the body is theme-token-based and overridable:
    the ``#viewer-md`` rules in :data:`DotoApp.CSS` colour ``MarkdownH1`` ..
    ``MarkdownH6`` from the contrast-tuned ``$text-*`` theme tokens
    (``$text-accent`` / ``$text-secondary`` / ``$text-error`` for H1/H2/H3 and
    ``$text`` for h4-h6) rather than hardcoded hex, so headings stay readable
    and visually distinct on every built-in theme (light/dark/ansi). A child
    :class:`DotoApp` can re-style them by overriding those ``#viewer-md``
    rules in its own ``CSS``.
    """

    #: Markdown widget class used to render the task body. A child theme can
    #: set this to a :class:`~textual.widgets.Markdown` subclass to customise
    #: body rendering without overriding :meth:`build_body_widget`.
    markdown_class: type[Markdown] = Markdown

    BINDINGS = [
        ("escape,enter", "close", "Close"),
        # Intentionally a DIRECT edit within this focused card-viewer modal
        # (distinct from the main app's two-key ``e e`` Edit domain). This
        # modal is self-contained and not routed through the prefix
        # dispatcher, so a bare ``e`` editing the viewed card is correct here;
        # do not "promote" it to a prefix.
        ("e", "edit", "Edit"),
        ("n", "edit_body", "Edit note"),
    ]

    def __init__(
        self,
        task: dict[str, Any],
        default_user: str = "",
        width_percent: int = 75,
    ) -> None:
        """Initialize the viewer for a task.

        Args:
            task: The task dict to display (carrying its display ``id``).
            default_user: The configured default user (``config.user`` falling
                back to ``config.default_assignee``), threaded through by
                :meth:`DotoApp._open_card_viewer`. It is the "boring default"
                for the RACI popup field: a RACI role assigned only to this
                user is suppressed (see :meth:`build_extra_field_lines`).
                Defaults to ``""`` (no default user) so the screen can still
                be constructed directly in tests; with no default user nothing
                is suppressed.
            width_percent: The modal's width as a percentage of the terminal
                width (applied in :meth:`on_mount`), from the configurable
                ``tui_modal_width_ratio`` (see
                :func:`doxtr_doto.cli.tui.actions.modal_width_percent`). Shares
                the same setting as the edit/note pop-ups so all three stay the
                same width. Defaults to ``75`` (3/4) so the screen can be
                constructed directly in tests.
        """
        super().__init__()
        self.view_task = task
        self.default_user = default_user
        self.width_percent = width_percent

    def on_mount(self) -> None:
        """Apply the configurable modal width (height stays as defined in CSS).

        The width is computed from the live terminal width (see
        :func:`_apply_modal_width`) so the viewer is exactly
        :attr:`width_percent` percent of the *total* terminal width - matching
        the edit/note pop-ups; the height is left untouched. :meth:`on_resize`
        re-applies it so the viewer tracks a terminal resize while open.
        """
        _apply_modal_width(
            self.query_one("#viewer-modal", Vertical), self.app.size.width, self.width_percent
        )

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the configurable width when the terminal is resized."""
        _apply_modal_width(
            self.query_one("#viewer-modal", Vertical), self.app.size.width, self.width_percent
        )

    @classmethod
    def build_detail_lines(cls, task: dict[str, Any]) -> list[str]:
        """Return the full-detail markup lines for a task (pure, testable).

        Delegates to the single-source line builder
        :func:`doxtr_doto.cli.output.build_task_detail_lines`, which is the
        same assembler the CLI ``doto list -f cards`` card uses
        (:meth:`doxtr_doto.cli.output.OutputFormatter.format_task_detail`). The
        viewer therefore shows exactly the field set/order/labels/styling of
        the CLI reference - id/title header, assignee, priority, status, due
        (overdue styled ``red bold``), tags, depends_on, series, created,
        updated and the body - and a new task field only has to be added in
        one place to appear in both surfaces. Free-text values are
        markup-escaped there so a title like ``"[WIP] fix"`` renders literally
        instead of being parsed as a style tag.

        A child theme can still override this classmethod to re-shape the
        viewer content without touching the shared CLI builder.

        Args:
            task: The task dict to render.

        Returns:
            The viewer's detail lines (rich/Textual markup).
        """
        return build_task_detail_lines(task)

    @classmethod
    def build_field_lines(cls, task: dict[str, Any]) -> list[str]:
        """Return only the *field* (style-markup) lines, excluding the body.

        These are the id/title header, assignee, priority, status, due, tags,
        depends_on, series, created and updated lines - everything
        :meth:`build_detail_lines` emits *except* the task body (and the blank
        separator before it). They carry rich/Textual *style* markup
        (``[bold]``, ``red bold``, ...), so they render into a soft-wrapping
        :class:`~textual.widgets.Static` rather than the Markdown body widget
        (Markdown would mangle the style tags).

        The split is derived from the single-source
        :meth:`build_detail_lines` so the field set/order/styling cannot drift
        from the CLI card: the shared builder always appends the body last as
        ``["", body]`` when ``task['body']`` is present, so the field lines are
        simply the detail lines with that trailing pair dropped.

        A child theme can override this to re-shape only the field region.

        Args:
            task: The task dict to render.

        Returns:
            The field lines (rich/Textual style markup), without the body.
        """
        lines = cls.build_detail_lines(task)
        if task.get("body"):
            # The shared builder appends the body as a trailing ``["", body]``
            # pair; drop it so only the style-markup field lines remain.
            return lines[:-2]
        return lines

    def build_extra_field_lines(self, task: dict[str, Any]) -> list[str]:
        """Return the popup-only extra field lines (RACI-differing, time spent).

        These lines are *not* part of the shared CLI card builder
        (:func:`doxtr_doto.cli.output.build_task_detail_lines`); they are
        viewer-only so they appear in this popup but never in the
        ``doto list -f cards`` reference card. They render into
        ``#viewer-detail`` immediately after :meth:`build_field_lines`.

        Two groups are emitted, each omitted when it has nothing to show:

        * **RACI differing from the default user** via the overridable
          :func:`doxtr_doto.raci.render_raci_differing_lines`, passing
          :attr:`default_user`. A role assigned only to the default user is
          suppressed (case-insensitive comparison); the remaining roles/names
          are grouped by role with the ``RACI_ROLE_LABELS`` labels. Empty when
          the task has no RACI, or every role is only the default user.
        * **Time spent** via the overridable
          :func:`doxtr_doto.cli.session.render_time_spent_line`, summing the
          task's ``worklogs``. An open session counts up to "now". Omitted
          when no time has been tracked.

        This is an instance method (not a classmethod) because it needs
        :attr:`default_user` from the screen; a child theme can override it to
        re-shape or drop the extra fields without touching the shared builder.
        It is compositional - mirroring how :meth:`build_detail_lines`
        delegates to :meth:`build_field_lines` - concatenating the per-field
        sub-methods :meth:`build_raci_differing_lines` and
        :meth:`build_time_spent_lines`, so a child theme can override, reorder,
        or drop one extra field by overriding just that sub-method (or this
        assembler) rather than reimplementing both.

        Args:
            task: The task dict to render.

        Returns:
            The extra field lines (rich/Textual style markup), possibly empty.
        """
        return self.build_raci_differing_lines(task) + self.build_time_spent_lines(task)

    def build_raci_differing_lines(self, task: dict[str, Any]) -> list[str]:
        """Return the popup-only RACI-differing extra field lines.

        One of the per-field sub-seams concatenated by
        :meth:`build_extra_field_lines`. Delegates to the overridable
        :func:`doxtr_doto.raci.render_raci_differing_lines`, passing
        :attr:`default_user`: a role assigned only to the default user is
        suppressed (case-insensitive comparison); the remaining roles/names
        are grouped by role with the ``RACI_ROLE_LABELS`` labels. Empty when
        the task has no RACI, or every role is only the default user.

        A child theme can override this one method to re-shape or drop the
        RACI extra field without touching the time-spent field or the
        assembler.

        Args:
            task: The task dict to render.

        Returns:
            The RACI-differing field lines (style markup), possibly empty.
        """
        return render_raci_differing_lines(task.get("raci"), self.default_user)

    def build_time_spent_lines(self, task: dict[str, Any]) -> list[str]:
        """Return the popup-only time-spent extra field line(s).

        One of the per-field sub-seams concatenated by
        :meth:`build_extra_field_lines`. Delegates to the overridable
        :func:`doxtr_doto.cli.session.render_time_spent_line`, summing the
        task's ``worklogs``; an open session counts up to "now". Returns an
        empty list when no time has been tracked (the renderer returns
        ``None``), so the field is omitted.

        A child theme can override this one method to re-shape or drop the
        time-spent extra field without touching the RACI field or the
        assembler.

        Args:
            task: The task dict to render.

        Returns:
            The time-spent field line(s) (style markup), empty when no time is
            tracked.
        """
        time_line = render_time_spent_line(task.get("worklogs") or [])
        if time_line is None:
            return []
        return [time_line]

    @classmethod
    def build_body_markdown(cls, task: dict[str, Any]) -> str | None:
        """Return the raw Markdown source for the task body (or ``None``).

        The body is handed to the body widget *verbatim* (not markup-escaped,
        unlike the body copy inside :meth:`build_detail_lines`, which is
        markup-escaped for the style-markup field path), so Markdown markup it
        contains - headings, lists, bold/italic, code - renders properly. When
        the task has no body this returns ``None`` and no body region is added.

        A child theme can override this to transform the body source before it
        is rendered.

        Args:
            task: The task dict to render.

        Returns:
            The body Markdown source, or ``None`` when there is no body.
        """
        body = task.get("body")
        if not body:
            return None
        return str(body)

    def build_body_widget(self, task: dict[str, Any]) -> Widget | None:
        """Build the body widget rendering the task's Markdown (or ``None``).

        Instantiates :attr:`markdown_class` (a :class:`~textual.widgets.Markdown`
        subclass by default) with the source from :meth:`build_body_markdown`,
        giving it the id ``viewer-md``. Returns ``None`` when the task has no
        body so :meth:`compose` adds no empty Markdown region.

        A child theme can override this (or just :attr:`markdown_class` /
        :meth:`build_body_markdown`) to replace the body rendering entirely,
        returning any :class:`~textual.widget.Widget` (not just a Markdown).
        This is deliberately an instance method (not a classmethod) so an
        override may use ``self`` / screen state when building the widget.

        Args:
            task: The task dict to render.

        Returns:
            The body widget (a :class:`~textual.widgets.Markdown` by default),
            or ``None`` when there is no body.
        """
        source = self.build_body_markdown(task)
        if source is None:
            return None
        return self.markdown_class(source, id="viewer-md")

    def compose(self) -> ComposeResult:
        """Build the viewer: field lines + a Markdown body in a scroll region.

        The field lines (:meth:`build_field_lines`) render into a
        soft-wrapping :class:`~textual.widgets.Static` (id ``viewer-detail``)
        so long titles/values wrap, followed by the popup-only extra fields
        (:meth:`build_extra_field_lines`: RACI differing from the default user
        and the time-spent line) in the same Static. The task body
        (:meth:`build_body_widget`, when present) renders into a
        :class:`~textual.widgets.Markdown` widget
        (id ``viewer-md``) so Markdown markup is displayed and prose wraps
        naturally. Both live in a :class:`~textual.containers.VerticalScroll`
        (id ``viewer-body``) that is ``height: 1fr`` so it fills the modal down
        to the docked hint and long content scrolls rather than overflowing.
        """
        with Vertical(id="viewer-modal"):
            with VerticalScroll(id="viewer-body"):
                field_lines = self.build_field_lines(self.view_task)
                extra_lines = self.build_extra_field_lines(self.view_task)
                yield Static(
                    "\n".join(field_lines + extra_lines),
                    id="viewer-detail",
                )
                body_widget = self.build_body_widget(self.view_task)
                if body_widget is not None:
                    yield body_widget
            yield Label(
                "[dim]Enter/Esc close \u00b7 e edit[/dim]",
                id="viewer-hint",
            )

    def action_close(self) -> None:
        """Close the viewer without opening the edit dialog."""
        self.dismiss(None)

    def action_edit(self) -> None:
        """Close the viewer and ask the app to open the edit dialog (Feature 4).

        Dismisses with the ``"edit"`` sentinel; the close-callback registered
        by :meth:`DotoApp._open_card_viewer` interprets it and opens the edit
        dialog via :meth:`DotoApp._open_edit` (which pushes
        :attr:`DotoApp.edit_task_screen_class`) for the same task, so the edit
        flow (and its :func:`doxtr_doto.cli.tui.actions.update_task` write +
        board refresh) is reused rather than reimplemented in the viewer.
        """
        self.dismiss("edit")

    def action_edit_body(self) -> None:
        """Close the viewer and open the focused body/note editor (``n``).

        Dismisses with the ``"note"`` sentinel; the close-callback registered
        by :meth:`DotoApp._open_card_viewer` interprets it and opens the
        body-only editor via :meth:`DotoApp._open_edit_body` (which pushes
        :attr:`DotoApp.edit_body_screen_class`) for the same task, so the
        note-editing flow (and its
        :func:`doxtr_doto.cli.tui.actions.update_task` write + board refresh)
        is reused rather than reimplemented in the viewer.
        """
        self.dismiss("note")


#: The flat (single-press) keys and their descriptions, the single source of
#: truth the top-level :class:`HelpScreen` renders (the stream keys come from
#: :data:`KEYMAP`). Kept here so the help text cannot drift from the flat
#: ``DotoApp.BINDINGS``.
FLAT_KEY_HELP: tuple[tuple[str, str], ...] = (
    ("j / k", "move cursor down / up (arrows mirror vim keys)"),
    ("Shift+Up/Down", "jump to top / bottom of the current list"),
    ("h / l", "prev / next lane (kanban) or day (calendar)"),
    ("Tab", "cycle panes (kanban: move card forward; calendar: regions)"),
    ("Shift+Tab", "cycle panes in reverse"),
    ("Enter", "open / reveal / activate the selected task"),
    ("Space", "expand/collapse sub-tasks (parent row) or select task (leaf)"),
    ("e", "edit the selected task"),
    ("n", "edit the selected task's note/body (Markdown)"),
    ("a", "add a task"),
    ("r", "add a recurring series (pattern + at/for + from/until dates)"),
    ("A", "calendar: assign the selected day as the no-due task's due date"),
    ("w", "start / stop working (status -> in-progress + focus timer)"),
    ("d", "mark done (flat alias of s d)"),
    ("D", "cycle status (flat alias of s n)"),
    ("v / V", "cycle task-list layout forward / reverse"),
    ("/", "filter / search tasks"),
    ("F", "filter & sort pop-up"),
    ("R", "rescan repositories"),
    ("g", "toggle Global / Local scope"),
    ("q", "quit"),
)


class HelpScreen(ModalScreen[None]):
    """Top-level keybinding help router.

    Lists the flat (single-press) keys and the stream domains, pointing to the
    per-domain help (``s?``/``t?``/``c?``/``S?``). Both this screen and
    :class:`DomainHelpScreen` derive their text from the shared flat-key table
    (:data:`FLAT_KEY_HELP`) and the :data:`KEYMAP` registry so the help can
    never drift from the dispatcher.
    """

    BINDINGS = [("escape,question_mark,q", "close", "Close")]

    def __init__(self, keymap: dict[str, DomainSpec] | None = None) -> None:
        """Store the stream registry to render (defaults to the global one).

        Args:
            keymap: The stream-domain registry to list. Defaults to the
                module-level :data:`KEYMAP`; a child theme that overrides
                :attr:`DotoApp.keymap` passes its own so the help never drifts
                from the app's actual dispatcher.
        """
        super().__init__()
        self._keymap = keymap if keymap is not None else KEYMAP

    def _body(self) -> str:
        """Return the top-level help markup (flat keys + stream domains)."""
        lines = ["[bold]doto TUI - keybindings[/bold]", ""]
        lines.append("[bold]Flat keys[/bold]")
        for key, desc in FLAT_KEY_HELP:
            lines.append(f"  {key:<14} {desc}")
        lines.append("")
        lines.append("[bold]Stream keys (press the prefix, then a sub-key)[/bold]")
        for prefix, spec in self._keymap.items():
            lines.append(f"  {prefix:<14} {spec.label} - press {prefix}? for its keys")
        lines.append("")
        lines.append("  ?              this help     Esc / q    close")
        lines.append("")
        lines.append("  Arrow keys mirror the vim keys in every layout.")
        lines.append("")
        lines.append("  In the card viewer popup (Enter on a list/kanban/calendar card):")
        lines.append("  Enter / Esc    close the viewer")
        lines.append("  e              close the viewer and edit the task")
        lines.append("")
        lines.append("  In the edit dialog (e):")
        lines.append("  Ctrl-K         kill (cut) to end of line")
        lines.append("  Ctrl-Y         yank (paste) killed text")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        """Build the modal's widgets."""
        yield Label(self._body(), id="help-label")

    def action_close(self) -> None:
        """Close the help modal."""
        self.dismiss(None)


class DomainHelpScreen(ModalScreen[None]):
    """Per-domain keybinding help, rendered from a :class:`DomainSpec`.

    Opened by ``s?``/``t?``/``c?``/``S?``. The title is the domain label and
    the body lists the domain's resolved :class:`KeyEntry` rows plus the
    ``?``/``Esc`` affordances, so it stays in lockstep with the dispatcher and
    the hint bar (all three read :data:`KEYMAP`).
    """

    BINDINGS = [("escape,question_mark,q", "close", "Close")]

    def __init__(self, prefix: str, domain_spec: Any, entries: Any) -> None:
        """Store the domain to render.

        Args:
            prefix: The domain prefix key (e.g. ``"s"``).
            domain_spec: The :class:`DomainSpec` for the domain (for its label).
            entries: The resolved :class:`KeyEntry` rows for the domain.
        """
        super().__init__()
        self._prefix = prefix
        self._domain_spec = domain_spec
        self._entries = entries

    def _body(self) -> str:
        """Return the per-domain help markup."""
        lines = [f"[bold]{self._domain_spec.label} ({self._prefix} › ...)[/bold]", ""]
        for entry in self._entries:
            lines.append(f"  {self._prefix} {entry.key:<10} {entry.label}")
        lines.append("")
        lines.append(f"  {self._prefix} ?           this help")
        lines.append("  Esc            cancel the prefix")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        """Build the modal's widgets."""
        yield Label(self._body(), id="help-label")

    def action_close(self) -> None:
        """Close the help modal."""
        self.dismiss(None)


class KickstartScreen(ModalScreen[str | None]):
    """The once-per-day kickstart nudge modal.

    Offers one-key shortcuts to start a top-priority candidate task
    (``1``..``N``), clock in to general work (``w``), open search (``/``), or
    skip (``esc``). The *decision* to show this modal and the candidate
    ranking live in :mod:`doxtr_doto.cli.tui.nudge` so they can be unit-tested
    without rendering; this screen only presents the choices and dismisses
    with the chosen action.

    Dismisses with one of: ``"1"``..``"N"`` (start that candidate), ``"work"``,
    ``"search"``, or ``"skip"`` (also used for ``esc``). The caller records
    ``last_prompt_date`` for *any* dismissal so the nudge fires at most once
    per day.
    """

    BINDINGS = [
        ("escape", "skip", "Skip"),
        ("w", "work", "Clock in"),
        ("slash", "search", "Search"),
    ]

    def __init__(self, candidates: list[nudge.Candidate]) -> None:
        """Initialize the modal with the candidate shortcuts.

        Args:
            candidates: The ranked candidate tasks to offer.
        """
        super().__init__()
        self.candidates = candidates

    def _body(self) -> str:
        """Build the modal body markup.

        Returns:
            The Textual markup string shown in the modal.
        """
        lines = ["[bold]Good day! Ready to start?[/bold]", ""]
        if self.candidates:
            lines.append("Start a task:")
            for candidate in self.candidates:
                lines.append(
                    f"  [bold]{escape_markup(candidate.key)}[/bold]  "
                    f"{escape_title(candidate.title, TitleHighlight.BRACKET_HIGHLIGHT_STYLE)}  "
                    f"({escape_markup(candidate.priority)})"
                )
        else:
            lines.append("No ready tasks found.")
        lines.extend(
            [
                "",
                "  [bold]w[/bold]  clock in to general work",
                "  [bold]/[/bold]  search tasks",
                "  [bold]esc[/bold]  skip for today",
            ]
        )
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        """Build the modal's widgets."""
        yield Label(self._body(), id="kickstart-label")

    def on_key(self, event: Any) -> None:
        """Dismiss with the pressed candidate digit, if it maps to a task.

        Candidate shortcuts are handled here (rather than via ``BINDINGS``)
        because the digit set is dynamic; the fixed ``w``/``/``/``esc`` keys
        stay in ``BINDINGS``.
        """
        valid = {c.key for c in self.candidates}
        if event.key in valid:
            event.stop()
            self.dismiss(event.key)

    def action_work(self) -> None:
        """Dismiss asking to clock in to general work."""
        self.dismiss("work")

    def action_search(self) -> None:
        """Dismiss asking to open the search modal."""
        self.dismiss("search")

    def action_skip(self) -> None:
        """Dismiss skipping the nudge."""
        self.dismiss("skip")


class AltLayoutSpec(NamedTuple):
    """One row of the data-driven alternative-layout registry.

    Collapses what used to be ~8 scattered per-layout branches in
    :class:`DotoApp` into a single source of truth, so adding a future
    alt-view touches ~1 registry row (plus the :class:`doxtr_doto.enums.TuiLayout`
    member and the shared :class:`doxtr_doto.cli.tui.widgets.AltLayoutView`
    CSS). The default table layout is intentionally *not* in the registry: it
    is the structural 3-pane ``#panes`` row, handled separately.

    Attributes:
        class_attr: Name of the overridable ``DotoApp`` class attribute
            holding the view's widget class (e.g. ``"list_view_class"``), so a
            child theme's swapped-in subclass is honored.
        dom_id: The widget's DOM id in ``compose`` (e.g. ``"list-view"``).
        rebuild: Adapter that rebuilds the view from the app's current task
            set, absorbing per-view ``rebuild`` signature differences (kanban
            also needs the configured statuses). It queries its own widget
            from ``app`` so the generic :class:`AltLayoutView` contract never
            needs to carry view-specific arguments.
        cycles_details: Whether ``Tab`` cycles focus between this view and the
            shared :class:`doxtr_doto.cli.tui.widgets.TaskDetails` pane
            (view <-> details). False for every current layout: the plain list
            layout is a single focusable view (so Tab stays on it), and the
            kanban and calendar layouts rebind ``Tab`` to their own
            ``tab_action`` (kanban moves a card between lanes; calendar cycles
            its grid / Due / No-due regions and the details pane). Kept as a
            data-driven flag - rather than a hard-coded per-layout branch - so
            a future alt-view can opt into the plain Tab-into-details cycle by
            setting it. Ignored when ``tab_action`` is set.
        tab_action: Optional ``(app, direction) -> None`` hook that overrides
            the default ``Tab``/``Shift+Tab`` handling for the view. When set,
            :meth:`DotoApp.action_cycle_pane` dispatches to it (and skips the
            ``cycles_details`` focus-cycle) so a view can bind ``Tab`` to its
            own action - e.g. kanban moves the selected card between lanes, and
            the calendar cycles its internal focus regions and the details
            pane (:meth:`DotoApp._cycle_calendar_region`) - without a
            hard-coded per-layout branch in the app. ``direction`` is ``+1``
            for ``Tab`` (forward) and ``-1`` for ``Shift+Tab``.
    """

    class_attr: str
    dom_id: str
    rebuild: Callable[[DotoApp], None]
    cycles_details: bool
    tab_action: Callable[[DotoApp, int], None] | None = None


class KeyEntry(NamedTuple):
    """One resolvable second key within a stream domain.

    The single source of truth for a stream's sub-keys: the dispatcher
    (:meth:`DotoApp.on_key` / :meth:`DotoApp._run_entry`), the hint bar
    (:class:`doxtr_doto.cli.tui.widgets.KeyHintBar`) and the help screens all
    read these rows, so they cannot drift. ``action`` is the ``DotoApp``
    action name (e.g. ``"set_status_open"`` / ``"cycle_status"``); ``label``
    is the shared hint-bar + help label.
    """

    key: str
    action: str
    label: str


class DomainSpec(NamedTuple):
    """One stream domain (prefix) in the :data:`KEYMAP` registry.

    Mirrors the :class:`AltLayoutSpec` discipline: a single data row drives the
    dispatcher, hint bar and help so the three consumers cannot diverge.

    Attributes:
        label: The bar/help label for the prefix (e.g. ``"State"``).
        kind: The domain's nature - ``"task"`` (its actions mutate the current
            task selection), ``"task_or_global"`` (a mix of task and global
            actions) or ``"global"`` (app-wide actions). This documents each
            domain's semantics; it is not read for dispatch (see
            :meth:`DotoApp._run_entry`, which routes by the entry's ``action``
            name so new sub-keys need no dispatcher branch).
        entries_fn: Builds the domain's :class:`KeyEntry` rows for a given app
            (status rows are dynamic, so this is a callable rather than a
            static list).
    """

    label: str
    kind: str
    entries_fn: Callable[[DotoApp], list[KeyEntry]]

    def lookup(self, app: DotoApp, key: str) -> KeyEntry | None:
        """Resolve a second ``key`` against this domain's live entries.

        Args:
            app: The running app (its ``ctx`` drives the dynamic status rows).
            key: The pressed second key.

        Returns:
            The matching :class:`KeyEntry`, or None when no entry owns ``key``.
        """
        for entry in self.entries_fn(app):
            if entry.key == key:
                return entry
        return None


class DotoApp(App[None]):
    """The doto 3-pane Textual application.

    Panes (the default table layout):

    * left - repo tree + favorites + scope indicator (:class:`RepoTree`),
    * right, upper - task list with running/done/priority/tag badges
      (:class:`TaskList`),
    * right, lower - task details + session interval log
      (:class:`TaskDetails`), stacked *below* the task list inside the
      ``#task-pane`` column; its share of the height is set by the ``c`` ->
      ``d`` detail-size ratio (see :meth:`apply_detail_ratio`).

    A persistent :class:`StatusLine` shows the two live counters (Layer-1 work
    clock and Layer-2 focus), refreshed on a Textual timer. A top-right
    :class:`TaskTimeLine` shows the current work-session elapsed time (the
    elapsed time of the single currently-open work-clock interval, distinct
    from the status line's daily work counter) and the total time spent on the
    currently highlighted task, refreshed on the same timer and whenever the
    task-list cursor moves.
    """

    CSS = """
    #panes {
        height: 1fr;
    }
    RepoTree {
        width: 28;
        border-right: solid $panel;
    }
    #task-pane {
        width: 2fr;
    }
    /* The task list and detail pane are stacked inside #task-pane. The real
       split is applied at runtime by DotoApp.apply_detail_ratio() from the
       persisted tui_detail_ratio (default actions.DEFAULT_DETAIL_RATIO); these
       static heights are only the pre-mount placeholder, so they are kept as
       a neutral even split to avoid a second, drift-prone copy of the default
       ratio. Selected by #id (not the TaskList/TaskDetails type) so a theme
       that swaps task_list_class / task_details_class for a non-subclass
       widget still picks up the layout styling. */
    #task-list {
        height: 1fr;
    }
    #task-details {
        height: 1fr;
        padding: 0 1;
        border-top: solid $panel;
    }
    StatusLine {
        height: 1;
        dock: bottom;
        background: $panel;
        padding: 0 1;
    }
    KeyHintBar {
        height: 1;
        dock: bottom;
        background: $panel-darken-1;
        padding: 0 1;
    }
    TaskTimeLine {
        height: 1;
        dock: top;
        content-align: right middle;
        background: $panel;
        padding: 0 1;
    }
    #alt-view {
        height: 1fr;
        padding: 0 1;
    }
    #time-pane {
        height: 1fr;
    }
    #time-view {
        width: 2fr;
    }
    #time-summary {
        width: 1fr;
        padding: 0 1;
        border-left: solid $panel;
    }
    AltLayoutView {
        height: 1fr;
        padding: 0 1;
    }
    AddTaskScreen, FilterScreen, HelpScreen, EditTaskScreen {
        align: center middle;
    }
    EditBodyScreen {
        align: center middle;
    }
    DomainHelpScreen {
        align: center middle;
    }
    ViewPrefsScreen {
        align: center middle;
    }
    DetailRatioScreen {
        align: center middle;
    }
    ModalWidthScreen {
        align: center middle;
    }
    SetParentScreen {
        align: center middle;
    }
    #detailratio-modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #detailratio-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #detailratio-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #modalwidth-modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #modalwidth-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #modalwidth-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #viewprefs-modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #viewprefs-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #viewprefs-repos {
        height: auto;
        max-height: 8;
        border: round $panel;
    }
    #viewprefs-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #setparent-modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #setparent-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #setparent-search {
        width: 100%;
        margin-bottom: 1;
    }
    #setparent-list {
        height: 12;
        max-height: 12;
        border: round $primary;
        margin-bottom: 1;
    }
    #setparent-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    CardViewerScreen {
        align: center middle;
    }
    KickstartScreen {
        align: center middle;
    }
    AddTaskScreen > Input, FilterScreen > Input {
        width: 60;
    }
    AddTaskScreen > Label, AddTaskScreen > Select {
        width: 60;
    }
    #add-modal {
        width: 70;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #add-body-scroll {
        height: 1fr;
    }
    #add-body {
        height: 8;
        border: round $panel;
    }
    #add-bottom {
        dock: bottom;
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #add-heading {
        text-style: bold;
        margin-bottom: 1;
    }
    #add-series-modal {
        width: 70;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #add-series-body {
        height: 1fr;
    }
    #add-series-bottom {
        dock: bottom;
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #add-series-heading {
        text-style: bold;
        margin-bottom: 1;
    }
    #edit-series-modal {
        width: 70;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #edit-series-body {
        height: 1fr;
    }
    #edit-series-bottom {
        dock: bottom;
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #edit-series-heading {
        text-style: bold;
        margin-bottom: 1;
    }
    #edit-series-context {
        color: $text-muted;
        margin-bottom: 1;
    }
    #confirm-modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #confirm-message {
        margin-bottom: 1;
    }
    #confirm-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #edit-modal {
        width: 70;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #edit-body {
        height: 1fr;
    }
    #edit-body-input {
        height: 8;
        border: round $panel;
    }
    #edit-bottom {
        dock: bottom;
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #edit-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #editbody-modal {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #editbody-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #editbody-input {
        height: 1fr;
        border: round $panel;
    }
    #editbody-bottom {
        dock: bottom;
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #viewer-modal {
        width: 70;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #viewer-body {
        height: 1fr;
    }
    #viewer-detail {
        width: 1fr;
    }
    #viewer-md {
        width: 1fr;
        height: auto;
        margin: 0;
        /* Keep a horizontal gutter for the body prose. Textual's default is
           ``padding: 0 2 0 2``; set it explicitly so it survives even if the
           default changes, without reintroducing the ``padding: 0`` that used
           to swallow the gutter. */
        padding: 0 2 0 2;
        /* Header colours derive from contrast-guaranteed theme tokens (not
           hardcoded hex) so headings stay readable and visually distinct on
           every built-in theme (light/dark/ansi). The ``$text-*`` family is
           auto-contrast-tuned against the surface, so these never collapse
           into the background the way the stock ``$markdown-h*-color`` tokens
           do on some dark/ansi themes (e.g. the invisible dark-blue H3 on
           ``ansi-dark``). ``$text-accent`` / ``$text-secondary`` /
           ``$text-error`` are mutually distinct on every built-in theme and
           deliberately avoid ``$text-primary`` (which maps to the dark navy
           ``ansi_blue`` on the ansi themes, the original invisible case).
           ``$text`` (the auto-contrast default foreground) is reused for
           h4-h6, differentiated by text-style. A child DotoApp can re-style
           these by overriding the ``#viewer-md`` rules in its own CSS. */
        MarkdownH1 { color: $text-accent; background: transparent; text-style: bold; }
        MarkdownH2 { color: $text-secondary; background: transparent; text-style: bold; }
        MarkdownH3 { color: $text-error; background: transparent; text-style: bold; }
        MarkdownH4 { color: $text; background: transparent; text-style: bold; }
        MarkdownH5 { color: $text; background: transparent; text-style: bold; }
        MarkdownH6 { color: $text; background: transparent; text-style: bold italic; }
    }
    #viewer-hint {
        dock: bottom;
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    #help-label {
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #kickstart-label {
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    BreaksConfigScreen, WorkTimeScreen, WorkIntervalEditScreen {
        align: center middle;
    }
    #breaks-modal, #interval-modal {
        width: 76;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #breaks-input {
        height: 14;
        border: round $panel;
    }
    #breaks-workweek-label {
        margin-top: 1;
        color: $text-muted;
    }
    #breaks-workweek {
        margin-bottom: 1;
    }
    #breaks-title, #interval-title, #worktime-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #breaks-help {
        margin-bottom: 1;
        color: $text-muted;
    }
    #interval-duration {
        margin-top: 1;
        color: $text-muted;
    }
    #breaks-bottom, #interval-bottom {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    #worktime-modal {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #worktime-body {
        height: 1fr;
    }
    #worktime-total {
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    #worktime-hint {
        dock: bottom;
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    WorkStatsScreen {
        align: center middle;
    }
    #workstats-modal {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #workstats-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #workstats-body {
        height: 1fr;
    }
    #workstats-hint {
        dock: bottom;
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    TaskTimeStatsScreen {
        align: center middle;
    }
    #taskstats-modal {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #taskstats-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #taskstats-body {
        height: 1fr;
    }
    #taskstats-hint {
        dock: bottom;
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    TaskSessionsScreen {
        align: center middle;
    }
    #tasksessions-modal {
        width: 80;
        height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #tasksessions-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #tasksessions-body {
        height: 1fr;
    }
    #tasksessions-total {
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    #tasksessions-hint {
        dock: bottom;
        height: auto;
        content-align: center middle;
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        # App-level arrow bindings for the TABLE layout's DataTable: the
        # alt views (AltLayoutView) re-bind these same arrow keys on
        # themselves to override VerticalScroll's native scroll actions, so
        # keep both sets - neither is redundant.
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        # Jump-to-edge navigation (parallel to the single-step up/down above):
        # Shift+Up jumps the active layout's cursor to the first entry and
        # Shift+Down to the last. Like the plain arrow bindings these are the
        # app-level copy for the TABLE layout's DataTable; the alt views
        # (AltLayoutView) re-bind the same keys on themselves to override
        # VerticalScroll, so keep both sets. Unlike Shift+Tab (which some
        # terminals deliver as the distinct ``back_tab`` key), Textual decodes
        # the physical Shift+Up / Shift+Down as ``shift+up`` / ``shift+down``,
        # so a single key name each is sufficient.
        ("shift+up", "cursor_top", "Jump to top"),
        ("shift+down", "cursor_bottom", "Jump to bottom"),
        ("tab", "cycle_pane", "Cycle pane / kanban: card forward"),
        # Bind both the ``shift+tab`` and the ``back_tab`` key names: Textual's
        # key decoding (and some terminals/multiplexers) may deliver the
        # physical Shift+Tab as the literal ``back_tab`` key rather than
        # ``shift+tab``, so binding only ``shift+tab`` makes reverse cycling
        # silently dead in those terminals. Both route to the same action.
        ("shift+tab", "cycle_pane_reverse", "Cycle pane (reverse) / kanban: card back"),
        ("back_tab", "cycle_pane_reverse", "Cycle pane (reverse) / kanban: card back"),
        ("space", "select", "Select"),
        ("d", "done", "Done"),
        ("D", "cycle_status", "Cycle status"),
        # ``e`` is now a PREFIX for the Edit stream domain (see the ``"e"``
        # entry in :data:`KEYMAP`), not a flat binding: ``e e`` edits the
        # selected entry, ``e d`` deletes it, and -- only when the selection
        # is a series occurrence -- ``e E`` / ``e D`` edit / delete the whole
        # series. The flat ``("e", "edit")`` binding was removed so the prefix
        # dispatcher (:meth:`on_key`) owns the key.
        ("n", "edit_body", "Edit note/body"),
        ("a", "add", "Add"),
        # Add a recurring *series* (NEW): opens the add-series dialog. The
        # lowercase ``r`` is chosen because the suggested ``R`` (Shift+R) is
        # already the rescan binding and ``r`` was unbound; it reads as "add
        # Recurring series".
        ("r", "add_series", "Add recurring series"),
        # Calendar layout: assign the selected day as the highlighted no-due
        # task's due date (Feature C). ``A`` (Shift+A) is chosen because the
        # lowercase ``a`` is already the add-task binding; ``A`` is unbound. A
        # no-op in other layouts / when no undated task is highlighted.
        ("A", "assign_due", "Assign due date (calendar)"),
        # Flat "start/stop working" (NEW): sets the doto in-progress and starts
        # the focus timer in one press (actions.start_work); a second press
        # stops the timer. The former single-key timer/work-clock keys now
        # live under the ``t`` stream (``t t``/``t o``/``t w``/``t e``), the
        # breaks configurator under ``c b``, and the stats pop-ups under
        # ``S w``/``S t`` - all intercepted by :meth:`DotoApp.on_key` before
        # these flat BINDINGS, so those keys are not bound here.
        ("w", "start_work", "Start/stop working"),
        ("v", "cycle_layout", "Cycle layout"),
        ("V", "cycle_layout_prev", "Cycle layout (reverse)"),
        ("enter", "activate", "Open / reveal"),
        ("h", "layout_move_prev", "Prev lane/day"),
        ("l", "layout_move_next", "Next lane/day"),
        # App-level left/right arrows for the TABLE layout; AltLayoutView
        # re-binds these on the alt views too (see the up/down note above).
        ("left", "layout_move_prev", "Prev lane/day"),
        ("right", "layout_move_next", "Next lane/day"),
        ("slash", "filter", "Filter"),
        # Filter/sort pop-up (Feature C). ``F`` (Shift+F) is chosen because the
        # lowercase ``f`` is unbound and ``/`` is the free-text filter; ``F``
        # reads as "Filter & sort".
        ("F", "view_prefs", "Filter & sort"),
        ("R", "rescan", "Rescan"),
        ("g", "toggle_scope", "Scope"),
        ("q", "quit", "Quit"),
    ]

    #: Overridable widget classes so a child app can replace rendering.
    repo_tree_class: type[RepoTree] = RepoTree
    task_list_class: type[TaskList] = TaskList
    task_details_class: type[TaskDetails] = TaskDetails
    status_line_class: type[StatusLine] = StatusLine
    #: Overridable context-sensitive bottom hint bar (replaces the generic
    #: Textual ``Footer``). Mirrors :attr:`status_line_class`; a child theme
    #: can swap it to restyle the key hints without rewriting the app.
    key_hint_bar_class: type[KeyHintBar] = KeyHintBar
    task_time_line_class: type[TaskTimeLine] = TaskTimeLine
    #: Overridable alternative-layout view classes (cycled with ``v``). Each
    #: is a pure-``format_*`` widget a child theme can swap to replace a
    #: layout's rendering without rewriting the app.
    list_view_class: type[ListView] = ListView
    kanban_view_class: type[KanbanView] = KanbanView
    calendar_view_class: type[CalendarView] = CalendarView
    time_view_class: type[TimeView] = TimeView
    #: Overridable right-side summary panel for the ``time`` layout (Feature:
    #: work-time summary). Rendered beside :attr:`time_view_class` in the
    #: ``#alt-view`` container; a child theme can swap it to replace the
    #: week/month/year summary rendering without rewriting the app.
    work_time_summary_class: type[WorkTimeSummary] = WorkTimeSummary
    kickstart_screen_class: type[KickstartScreen] = KickstartScreen
    edit_task_screen_class: type[EditTaskScreen] = EditTaskScreen
    #: Overridable body-editor modal (the ``n`` quick key): a focused,
    #: full-height text area editing only the task's Markdown ``body``/notes.
    #: Mirrors :attr:`edit_task_screen_class` so a child theme can swap it.
    edit_body_screen_class: type[EditBodyScreen] = EditBodyScreen
    #: Overridable add-task modal screen: the field-configurable modal opened
    #: by ``a`` that prompts for a new task's fields (which fields it shows is
    #: driven by ``tui_add_fields`` / ``tui_add_defaults``) and its target
    #: repository. A child theme can swap it without rewriting the app,
    #: mirroring :attr:`edit_task_screen_class`.
    add_task_screen_class: type[AddTaskScreen] = AddTaskScreen
    #: Overridable add-series modal screen: the dialog opened by ``r`` that
    #: prompts for a new recurring series' pattern (with ``at`` / ``for``
    #: suffixes via dedicated start-time / duration fields), its from/until
    #: dates and its target repository, then creates the series via the same
    #: reusable :func:`doxtr_doto.cli.tui.actions.add_series` the CLI
    #: ``doto add --repeat`` path uses. A child theme can swap it without
    #: rewriting the app, mirroring :attr:`add_task_screen_class`.
    add_series_screen_class: type[AddSeriesScreen] = AddSeriesScreen
    #: Overridable edit-series modal: edits an existing series from the
    #: selected occurrence forward, then applies the forward-only re-stamp via
    #: the same reusable :func:`doxtr_doto.cli.tui.actions.update_series` the
    #: CLI ``doto series update`` path uses. Mirrors
    #: :attr:`add_series_screen_class`.
    edit_series_screen_class: type[EditSeriesScreen] = EditSeriesScreen
    #: Overridable yes/no (or three-way) confirmation modal, used by the
    #: single-entry delete (``e d``) and the series delete (``e D``). Mirrors
    #: :attr:`edit_task_screen_class`.
    confirm_screen_class: type[ConfirmScreen] = ConfirmScreen
    #: Overridable calendar-sync conflict resolver modal (keep local/remote/both).
    conflict_resolve_screen_class: type[ConflictResolveScreen] = ConflictResolveScreen
    #: Overridable "card viewer" popup screen (Feature 3): the modal opened by
    #: ``Enter`` on a kanban card that lists a task's full detail. Mirrors
    #: :attr:`edit_task_screen_class` so a child theme can swap it.
    card_viewer_screen_class: type[CardViewerScreen] = CardViewerScreen
    #: Overridable filter/sort pop-up screen (Feature C): the modal opened by
    #: ``F`` that configures the task-list filters and sort. A child theme can
    #: swap it without rewriting the app, mirroring
    #: :attr:`edit_task_screen_class`.
    view_prefs_screen_class: type[ViewPrefsScreen] = ViewPrefsScreen

    #: Overridable parent-picker modal (``e P``). Lets the user attach the
    #: selected task(s) to a PARENT task (the :data:`TaskData` ``parent``
    #: link, distinct from ``depends_on``). A child theme can swap it without
    #: rewriting the app, mirroring :attr:`view_prefs_screen_class`; its
    #: dropdown widget is itself overridable via
    #: :attr:`SetParentScreen.select_class`.
    set_parent_screen_class: type[SetParentScreen] = SetParentScreen

    #: Overridable detail-pane ratio configurator (``c d``). Lets the user set
    #: how much of the total table-layout height the detail pane takes.
    detail_ratio_screen_class: type[DetailRatioScreen] = DetailRatioScreen
    #: Overridable task pop-up width configurator (``c m``). Lets the user set
    #: the card-viewer, edit-task and edit-note pop-up width as a fraction of
    #: the terminal width, mirroring :attr:`detail_ratio_screen_class`.
    modal_width_screen_class: type[ModalWidthScreen] = ModalWidthScreen

    #: Overridable time-management screens (Feature: work-hours reporting).
    #: ``c b`` opens the breaks configurator; ``t w`` opens the work-time
    #: interval manager. A child theme can swap either without rewriting the
    #: app, mirroring :attr:`edit_task_screen_class`.
    breaks_config_screen_class: type[BreaksConfigScreen] = BreaksConfigScreen
    work_time_screen_class: type[WorkTimeScreen] = WorkTimeScreen
    #: Overridable statistics pop-up (Feature: work statistics). Opened from
    #: the ``time`` layout with ``S w``; shows per-period numbers and text/ASCII
    #: bar charts. A child theme can swap it without rewriting the app.
    work_stats_screen_class: type[WorkStatsScreen] = WorkStatsScreen
    #: Overridable per-doto time-reporting pop-up (per-doto time stats).
    #: Opened from the ``time`` layout with ``S t``; shows per-period per-doto
    #: and per-repo worked-time bar charts. A child theme can swap it without
    #: rewriting the app, mirroring :attr:`work_stats_screen_class`.
    task_time_stats_screen_class: type[TaskTimeStatsScreen] = TaskTimeStatsScreen
    #: Overridable per-doto session editor modal. Opened with ``t e`` on the
    #: highlighted task (from the task-centric layouts); edits that single
    #: doto's recorded focus sessions. A child theme can swap it without
    #: rewriting the app, mirroring :attr:`work_time_screen_class`.
    task_sessions_screen_class: type[TaskSessionsScreen] = TaskSessionsScreen
    #: Overridable help screens (keystream keymap). ``?`` opens the top-level
    #: router; ``s?``/``t?``/``c?``/``S?`` open the per-domain help. Both derive
    #: their text from ``KEYMAP`` + the flat-key table so help cannot drift from
    #: the dispatcher; a child theme can swap either without rewriting the app,
    #: mirroring :attr:`edit_task_screen_class`.
    help_screen_class: type[HelpScreen] = HelpScreen
    domain_help_screen_class: type[DomainHelpScreen] = DomainHelpScreen

    #: Overridable stream-domain registry (the two-key keymap). Bound to the
    #: module-level :data:`KEYMAP` just after it is defined (KEYMAP is declared
    #: below the class, so it is attached via ``DotoApp.keymap = KEYMAP`` after
    #: the class body rather than referenced here). A child theme subclasses
    #: :class:`DotoApp` and sets its own, e.g.
    #: ``keymap = {**DotoApp.keymap, "X": DomainSpec(...)}`` to add a domain, or
    #: a filtered copy to remove/relabel one, without editing core. The
    #: dispatcher (:meth:`on_key`), hint bar, and help screens all read through
    #: this attribute, so overriding it keeps the three in lockstep -- mirroring
    #: the ``*_screen_class`` override seams above and the
    #: :func:`~doxtr_doto.calsync.providers.register_provider` registry pattern.
    keymap: dict[str, DomainSpec]

    #: Overridable filter/sort pipeline step seams (Features A/C). Each is a
    #: ``staticmethod`` wrapper over the matching
    #: :mod:`doxtr_doto.cli.tui.filtersort` function, passed into
    #: :func:`~doxtr_doto.cli.tui.filtersort.apply_view_prefs` by
    #: :meth:`_visible_tasks`. A child theme swaps exactly one pipeline step by
    #: setting one attribute (e.g. a no-op ``pin_active_first``), mirroring the
    #: ``*_class`` widget/screen seam, without re-implementing ``_visible_tasks``.
    apply_filters = staticmethod(filtersort.apply_filters)
    apply_sort = staticmethod(filtersort.apply_sort)
    pin_active_first = staticmethod(filtersort.pin_active_first)

    #: Data-driven registry of the alternative (non-table) layout views, the
    #: single source of truth that replaces the former per-layout branches in
    #: :meth:`_active_view`, :meth:`compose`, :meth:`apply_layout`, and
    #: :meth:`_rebuild_alt_views`. Adding a future view is ~1 row here (plus a
    #: :class:`doxtr_doto.enums.TuiLayout` member and the shared
    #: :class:`doxtr_doto.cli.tui.widgets.AltLayoutView` CSS). ``TABLE`` is
    #: deliberately absent: it is the structural ``#panes`` row.
    ALT_LAYOUTS: dict[TuiLayout, AltLayoutSpec] = {
        TuiLayout.LIST: AltLayoutSpec(
            "list_view_class",
            "list-view",
            lambda app: app.query_one(app.list_view_class).rebuild(app._tasks, app._collapsed_ids),
            cycles_details=False,
        ),
        TuiLayout.KANBAN: AltLayoutSpec(
            "kanban_view_class",
            "kanban-view",
            lambda app: app.query_one(app.kanban_view_class).rebuild(
                app._tasks, list(app._kanban_statuses())
            ),
            cycles_details=False,
            tab_action=lambda app, direction: app._kanban_move(direction),
        ),
        TuiLayout.CALENDAR: AltLayoutSpec(
            "calendar_view_class",
            "calendar-view",
            lambda app: app.query_one(app.calendar_view_class).rebuild(app._tasks),
            cycles_details=False,
            tab_action=lambda app, direction: app._cycle_calendar_region(direction),
        ),
        TuiLayout.TIME: AltLayoutSpec(
            "time_view_class",
            "time-view",
            lambda app: app._rebuild_time_layout(),
            cycles_details=False,
        ),
    }

    #: The CLI context (store, config, global state). Annotated at class level
    #: so the ``ALT_LAYOUTS`` registry lambdas (evaluated in the class body)
    #: can reference ``app.ctx`` with a known type; assigned in :meth:`__init__`.
    ctx: DotoContext

    def __init__(self, ctx: DotoContext, **kwargs: Any) -> None:
        """Initialize the app for a CLI context.

        Args:
            ctx: The CLI context (store, config, global state).
            **kwargs: Passed through to :class:`textual.app.App`.
        """
        super().__init__(**kwargs)
        self.ctx = ctx
        self.scope = DisplayScope.GLOBAL
        self.filter_term = ""
        self._tasks: list[dict[str, Any]] = []
        #: Session-scoped set of parent task ids whose sub-tasks are COLLAPSED
        #: (hidden) in the task list tree. Parents not in this set default to
        #: EXPANDED (children visible), so newly-created parents show their
        #: children without any action. Tracked here (not persisted) like other
        #: transient view state; Space toggles membership for the cursor's
        #: parent row (see :meth:`action_select`). Passed into
        #: :meth:`~doxtr_doto.cli.tui.widgets.TaskList.rebuild` each refresh and
        #: pruned to still-visible ids there is unnecessary - a stale id simply
        #: has no effect until that parent reappears.
        self._collapsed_ids: set[str] = set()
        #: The active task-list layout, seeded from the persisted preference
        #: (defaults to the table view when none is saved - backward compat).
        self.layout_view: TuiLayout = actions.load_tui_layout(ctx)
        #: The persisted filter/sort preferences (Feature C), loaded on start
        #: so the last filter/sort state is remembered across sessions.
        self.view_prefs: ViewPrefs = actions.load_view_prefs(ctx)
        #: The persisted table-layout detail-pane ratio (an ``"n/d"`` string;
        #: the lower detail pane takes ``n/d`` of the total height, the task
        #: list the remaining ``(d-n)/d``). Loaded on start so the last chosen
        #: ratio is restored across sessions; defaults to
        #: :data:`actions.DEFAULT_DETAIL_RATIO`.
        self.detail_ratio: str = actions.load_detail_ratio(ctx)
        self.modal_width_ratio: str = actions.load_modal_width_ratio(ctx)
        #: The pending stream prefix for the two-key dispatcher (None when no
        #: prefix is armed). Set by :meth:`on_key` when a prefix key is
        #: pressed; cleared by :meth:`_clear_pending` once the second key
        #: resolves it (or ``escape``/an unknown key cancels). See the
        #: :data:`KEYMAP` stream registry and the dispatcher in :meth:`on_key`.
        self._pending: str | None = None

        #: Session-scoped memory of the last task chosen as a PARENT via the
        #: ``e P`` set-parent picker. Pre-selects the picker's dropdown on
        #: reopen (when the remembered task still exists), so attaching several
        #: tasks to the SAME parent in a row is fast. Intentionally NOT
        #: persisted across launches (the feature only requires session-scoped
        #: memory); it is reset to None here on each app start.
        self._last_parent_id: str | None = None

    def compose(self) -> ComposeResult:
        """Build the app layout.

        The default 3-pane table lives in ``#panes``; the alternative layout
        views (list/kanban/calendar) share the ``#alt-view`` container and are
        shown one at a time by :meth:`apply_layout`. The ``time`` layout is a
        two-pane split inside ``#alt-view``: the :attr:`time_view_class` day
        list on the left and the :attr:`work_time_summary_class`
        week/month/year summary on the right (``#time-pane``).
        """
        yield Header()
        yield self.task_time_line_class(id="task-time-line")
        with Horizontal(id="panes"):
            yield self.repo_tree_class("Scope", id="repo-tree")
            # The task list sits on top of the details pane in a vertical
            # split so the selected task's detail information renders *under*
            # the task list rather than to its right.
            with Vertical(id="task-pane"):
                yield self.task_list_class(id="task-list")
                yield self.task_details_class(id="task-details")
        with Vertical(id="alt-view"):
            for layout, spec in self.ALT_LAYOUTS.items():
                if layout is TuiLayout.TIME:
                    # The time layout pairs the day list with the summary
                    # panel in a horizontal split so the summary sits to the
                    # right of the day list.
                    with Horizontal(id="time-pane"):
                        yield getattr(self, spec.class_attr)(id=spec.dom_id)
                        yield self.work_time_summary_class(id="time-summary")
                else:
                    yield getattr(self, spec.class_attr)(id=spec.dom_id)
        yield self.status_line_class(id="status-line")
        # Both the StatusLine and the KeyHintBar dock to the bottom. Textual
        # stacks bottom-docked widgets in *declaration* order (first declared
        # sits higher), so yielding the hint bar AFTER the status line places
        # it at the very bottom row, with the live counters just above it.
        yield self.key_hint_bar_class(id="key-hint-bar")

    def on_mount(self) -> None:
        """Populate panes, start the live-counter timer, and maybe nudge."""
        self._set_terminal_title()
        #: Cached reference to the context-sensitive hint bar, painted to its
        #: idle state on mount. The dispatcher repaints it (domain on a pending
        #: prefix, idle on clear) through this handle.
        self._hintbar = self.query_one(self.key_hint_bar_class)
        self._hintbar.show_idle(self.keymap)
        self.refresh_repos()
        # Must publish the accent highlights (title bracket runs *and* the
        # selected kanban frame) *before* the first refresh_tasks so the
        # initial render already colours them.
        self.refresh_accent_highlights()
        self.apply_layout()
        self.apply_detail_ratio()
        self.refresh_tasks()
        self.refresh_counters()
        self.set_interval(COUNTER_INTERVAL, self.refresh_counters)
        self._focus_active_view()
        self.maybe_show_kickstart()

    def _set_terminal_title(self) -> None:
        """Label the terminal tab/window with :data:`TERMINAL_TITLE`.

        Writes the ``OSC 0`` escape sequence (``\\033]0;<title>\\007``) through
        the running Textual driver so the terminal tab shows the configured
        title (e.g. ``[DoTO]``) instead of the host process name (``python3``).

        Done here, inside ``on_mount`` rather than before :meth:`App.run`, so
        the sequence is emitted *after* Textual has taken over the terminal
        (entered the alternate screen); a title set before that is clobbered by
        Textual's startup reset. The write goes through ``self._driver`` which
        is the only output path that is safe while the app owns the screen.

        The title is *also* re-asserted on the recurring counter timer (see
        :meth:`refresh_counters`). Some terminals - notably the VS Code
        integrated terminal with ``terminal.integrated.tabs.title`` set to
        ``${sequence}`` - reset the tab label to the detected foreground
        process name (``python3``) when the child process is (re)detected,
        which can race with and clobber a title set only once at mount.
        Re-emitting the identical sequence periodically is invisible (setting a
        title never flickers) and keeps the configured label winning over the
        terminal's process-name fallback.

        The call is best-effort: if the driver is not in application mode
        (headless/test runs) or the write fails, the title is simply left as
        the default - relabelling the tab is cosmetic and must never crash the
        TUI.
        """
        driver = getattr(self, "_driver", None)
        if driver is None:
            return
        try:
            driver.write(f"\033]0;{TERMINAL_TITLE}\007")
        except (AssertionError, OSError, ValueError):
            # Driver not in application mode (headless/test) or output gone;
            # the tab label is cosmetic, so swallow and carry on.
            pass

    def resolve_accent(self) -> str:
        """Return the active theme accent used by the accent highlights.

        The shared *default* decision hook (mirroring how
        :meth:`KanbanView.frame_style` returns a style the drawing code then
        applies): both per-surface hooks (:meth:`resolve_frame_accent` and
        :meth:`resolve_bracket_accent`) default to this one, so a child app
        that wants *both* accent highlights - the title ``[...]`` bracket runs
        and the selected kanban card's frame - to share a different source
        (e.g. ``self.current_theme.primary`` or a user-configured colour)
        overrides this one line and both follow, without re-implementing the
        publish plumbing in :meth:`refresh_accent_highlights`.

        Returns:
            A concrete markup colour (hex) for the accent highlights, or an
            empty string to disable them. Defaults to the active theme's
            accent - the hue the Textual footer uses for key labels like
            ``tab``.
        """
        return self.current_theme.accent or ""

    def resolve_frame_accent(self) -> str:
        """Return the accent for the selected kanban card's frame (seam).

        The per-surface decision hook for
        :attr:`~doxtr_doto.cli.tui.widgets.KanbanView.SELECTED_FRAME_ACCENT`.
        In the common case it shares :meth:`resolve_accent` (both highlights
        are the same hue by default), but a child app can override just this
        one to vary the source per surface (e.g. frame =
        ``self.current_theme.primary``) without re-implementing the publish
        plumbing in :meth:`refresh_accent_highlights`.

        Returns:
            A concrete markup colour (hex) for the selected-frame accent, or
            an empty string to disable it.
        """
        return self.resolve_accent()

    def resolve_bracket_accent(self) -> str:
        """Return the accent for the title ``[...]`` bracket runs (seam).

        The per-surface decision hook for
        :attr:`~doxtr_doto.cli.tui.widgets.TitleHighlight.BRACKET_HIGHLIGHT_STYLE`.
        In the common case it shares :meth:`resolve_accent` (both highlights
        are the same hue by default), but a child app can override just this
        one to vary the source per surface (e.g. brackets =
        ``self.current_theme.secondary``) without re-implementing the publish
        plumbing in :meth:`refresh_accent_highlights`.

        Returns:
            A concrete markup colour (hex) for the bracket accent, or an empty
            string to disable it.
        """
        return self.resolve_accent()

    def refresh_accent_highlights(self) -> None:
        """Resolve the theme accent and publish it to the accent highlights.

        Resolves each highlight via its own decision hook and publishes the
        concrete hex to the two overridable class-attribute seams:

        * :attr:`~doxtr_doto.cli.tui.widgets.TitleHighlight.BRACKET_HIGHLIGHT_STYLE`
          - resolved via :meth:`resolve_bracket_accent`; the ``format_*``
          title renderers colour ``[...]`` runs with it;
        * :attr:`~doxtr_doto.cli.tui.widgets.KanbanView.SELECTED_FRAME_ACCENT`
          - resolved via :meth:`resolve_frame_accent`;
          :meth:`KanbanView.frame_style` draws the selected card's frame in
          it.

        Both hooks default to :meth:`resolve_accent` (same hue), so the common
        case stays DRY while a child app can override one hook to vary the
        source per surface. Each resolution is guarded independently: a failing
        hook degrades *that* highlight to ``""`` (disabled) rather than
        crashing the render.

        Writing them on the shared mixin / view classes means every widget
        (that does not override the attribute itself) picks the accent up. The
        colour is a concrete hex so it resolves in both Rich (kanban/DataTable
        width measurement) and Textual markup. Called at mount and on every
        theme change (:meth:`watch_theme`). Note a child theme's *subclass*
        attribute override survives, but mutating the base class attribute is
        overwritten on the next theme change - the live app republishes onto
        the base class here.
        """
        try:
            bracket = self.resolve_bracket_accent()
        except AttributeError:
            # A theme object without an ``accent`` (or pre-init theme state)
            # just disables the highlight rather than crashing the render.
            bracket = ""
        try:
            frame = self.resolve_frame_accent()
        except AttributeError:
            frame = ""
        TitleHighlight.BRACKET_HIGHLIGHT_STYLE = bracket or ""
        KanbanView.SELECTED_FRAME_ACCENT = frame or ""

    def watch_theme(self, theme: str) -> None:
        """Re-resolve the accent and rebuild views when the theme changes.

        ``theme`` is a Textual reactive; switching themes (the command
        palette's *Change theme*) fires this so the accent highlights (title
        bracket runs *and* the selected kanban frame) pick up the new accent
        immediately. Guarded against the pre-mount reactive set (``is_running``
        is False until the app loop starts), when :meth:`on_mount` performs the
        initial resolve + build.
        """
        if not self.is_running:
            return
        self.refresh_accent_highlights()
        self.refresh_tasks()

    # ------------------------------------------------------------------
    # Layout views (table / list / kanban / calendar)
    # ------------------------------------------------------------------
    def _active_view(self) -> AltLayoutView | None:
        """Return the active *alternative*-layout view, or None for the table.

        Returns:
            The list/kanban/calendar :class:`AltLayoutView` widget backing the
            current layout's selection, resolved from the single
            :attr:`ALT_LAYOUTS` registry. Returns None for
            :attr:`TuiLayout.TABLE`, which is the structural 3-pane layout
            backed by :attr:`task_list_class` rather than an alt-view (see
            :meth:`_current_selected_id` / :meth:`_focus_active_view`).
        """
        spec = self.ALT_LAYOUTS.get(self.layout_view)
        if spec is None:
            return None
        return self.query_one(f"#{spec.dom_id}", AltLayoutView)

    def _current_selected_id(self) -> str | None:
        """Return the selected task id for whichever layout is active.

        Returns:
            The active view's selected id, or None when nothing is selectable.
        """
        view = self._active_view()
        if view is None:
            return self.query_one(self.task_list_class).selected_id()
        return view.selected_id()

    def _selected_is_series_member(self) -> bool:
        """Return True when the current selection is part of a recurring series.

        Drives the dynamic ``e`` Edit domain: the whole-series entries
        (``e E`` edit series / ``e D`` delete series) are offered ONLY when the
        selected task carries a ``series_id``; a standalone task's Edit domain
        shows just ``e e`` / ``e d``. No selection yields False (so the menu
        falls back to the entry-only form).

        Returns:
            True when a task is selected and it belongs to a series.
        """
        selected = self._current_selected_id()
        if not selected:
            return False
        task = actions.find_task(self.ctx, self._action_ref(selected))
        return bool(task and task.get("series_id"))

    def select_task(self, task_id: str) -> bool:
        """Select (highlight + scroll into view) the task with id ``task_id``.

        The app-level, overridable seam used to reveal a specific task - in
        particular a freshly created one (see :meth:`action_add` and the
        ``tui_auto_select_new_task`` config). It delegates the actual cursor
        move to whichever view is active (the structural
        :attr:`task_list_class` table for :attr:`TuiLayout.TABLE`, otherwise
        the active :class:`~doxtr_doto.cli.tui.widgets.AltLayoutView`) via that
        view's overridable
        :meth:`~doxtr_doto.cli.tui.widgets.AltLayoutView.select_id` seam, so a
        child theme can swap either the per-view selection or this whole
        operation by subclassing and swapping the matching ``*_view_class`` /
        ``task_list_class`` attribute, or by overriding this method.

        Alternate selection *strategies* (e.g. select-then-scroll-to-top, or
        select-then-enter-edit) are intended to be composed by overriding this
        method - the per-view :meth:`select_id` seam owns row *placement*,
        while strategy variation lives here.

        Scope-robustness: :func:`doxtr_doto.cli.tui.actions.add_task` returns a
        *bare* local id, but the id the views report and store in their rows is
        the *display* id, which :func:`doxtr_doto.cli.display.apply_scope`
        namespaces (``repo#id``) in GLOBAL scope when a base prefix is not
        unique. So the bare id is first mapped to the display id present in the
        current (possibly filtered) :attr:`_tasks` set by matching the
        preserved ``_local_id`` for the current repo; the resolved display id
        (or the bare id itself in LOCAL scope / when already a display id) is
        then handed to the active view. When the created task is not in the
        visible set (e.g. filtered out), no row matches and this is a no-op.

        Args:
            task_id: The id of the task to select. Accepts the bare local id
                returned by :func:`add_task` or an already-namespaced display
                id.

        Returns:
            True when a matching row was found and selected, False otherwise.
        """
        display_id = self._display_id_for(task_id)
        view = self._active_view()
        if view is None:
            return self.query_one(self.task_list_class).select_id(display_id)
        return view.select_id(display_id)

    def _display_id_for(self, task_id: str) -> str:
        """Map a bare / namespaced id to the display id used by the views.

        The inverse direction of :meth:`_action_ref`: the views key their rows
        on the *display* id (bare in LOCAL scope, possibly ``repo#id`` in
        GLOBAL scope - see :func:`doxtr_doto.cli.display.apply_scope`), while
        :func:`doxtr_doto.cli.tui.actions.add_task` returns a bare local id. A
        task created in the current repo therefore needs its bare id resolved
        to whatever display id the current scope assigned it.

        The mapping is derived from the gathered :attr:`_tasks`, which carry
        both the preserved ``_local_id`` and the display ``id``: when a row for
        the current repo has ``_local_id == task_id`` its display ``id`` is
        returned. Falls back to ``task_id`` unchanged when no such row exists
        (the task is filtered out, or ``task_id`` is already a display id).

        Args:
            task_id: A bare local id (as returned by ``add_task``) or an
                already-namespaced display id.

        Returns:
            The display id the active view uses for that task, or ``task_id``
            unchanged when it cannot be mapped.
        """
        current = data.current_repo_name(self.ctx)
        return self._display_id_for_repo(current, task_id)

    def _action_ref(self, selected: str) -> str:
        """Return the task ref to use for a mutating action on ``selected``.

        The *displayed* id (what the user sees and what view widgets report as
        their selection) is deliberately shortened in GLOBAL scope by
        :func:`doxtr_doto.cli.display.apply_scope` when a task's base prefix is
        unique in the current view. That shortened string is a *display* value
        only: a bare id resolves (via
        :func:`doxtr_doto.cli.id_resolver.resolve_task_ref`) against the
        *current* repo's store, so passing a shortened FOREIGN-repo id
        straight into an action would misresolve it to the current repo.

        To keep mutations unambiguous without regressing the common
        single-repo case, the action ref is derived from the preserved
        ``_repo`` / ``_local_id`` tags on the gathered task:

        * a task owned by the *current* repo resolves against ``ctx.store``
          directly, so its ref is the bare ``_local_id`` (a canonical
          ``repo#id`` here would force a registry lookup that need not exist
          in LOCAL scope);
        * a *foreign* repo's task is returned as the canonical
          ``repo#id`` so :func:`resolve_task_ref` routes it to the owning
          repo's store via the registry.

        Do not "simplify" this to pass the display id directly — that
        reintroduces the foreign-repo resolution bug. Falls back to the
        selected id itself when the task is untagged or not present in the
        current (possibly filtered) task set.

        Args:
            selected: The selected (display) task id.

        Returns:
            A ref that :func:`resolve_task_ref` maps to the owning repo.
        """
        # This lookup keys on the display id and relies on
        # :func:`doxtr_doto.cli.display.apply_scope` guaranteeing that bare
        # display ids are unique within a view: equal bare ids imply equal base
        # prefixes, which forces that whole group to be namespaced. If the
        # shortening rule is ever loosened, this ``next()`` could bind the
        # wrong task.
        task = next((t for t in self._tasks if t.get("id") == selected), None)
        if task is None:
            return selected
        repo = task.get("_repo")
        local_id = task.get("_local_id")
        if not (repo and local_id):
            return selected
        if repo == data.current_repo_name(self.ctx):
            # Current repo's task resolves against ctx.store with its bare id.
            return str(local_id)
        return namespaced(repo, local_id)

    # -- Two-key stream dispatcher ------------------------------------------

    def _status_key_entries(self) -> list[KeyEntry]:
        """Build the ``s``-domain status rows from the configured statuses.

        Reads :func:`doxtr_doto.cli.tui.actions.status_cycle` (which prefers
        ``ctx.config.statuses``, falling back to
        :data:`doxtr_doto.constants.STATUS_DISPLAY_ORDER`) so the status
        sub-keys track the user's configured statuses rather than being
        hard-coded. Key assignment:

        1. The candidate key is the status' first letter (lowercased).
        2. On a first-letter collision the later status takes its first
           *unused* letter from the remaining letters of its own name; if none
           is free it falls back to the next unused ``a..z`` letter. The
           resolved key is what the hint bar and help display, so the mapping
           is never hidden.

        Each status maps to a per-status action name
        ``set_status_<normalized-name>`` (``normalized`` replaces ``-`` with
        ``_``) with label ``STATUS_LABELS.get(status, title-cased name)``.

        Default statuses yield ``o`` -> Open, ``i`` -> In Progress,
        ``b`` -> Blocked, ``d`` -> Done.

        Returns:
            The generated :class:`KeyEntry` rows, one per configured status.
        """
        used: set[str] = set()
        entries: list[KeyEntry] = []
        for status in actions.status_cycle(self.ctx):
            key = self._pick_status_key(status, used)
            used.add(key)
            normalized = status.replace("-", "_")
            label = STATUS_LABELS.get(status, status.replace("-", " ").title())
            entries.append(KeyEntry(key, f"set_status_{normalized}", label))
        return entries

    @staticmethod
    def _pick_status_key(status: str, used: set[str]) -> str:
        """Return an unused sub-key for ``status`` (see :meth:`_status_key_entries`).

        Args:
            status: The status name.
            used: The already-assigned keys (mutated by the caller after use).

        Returns:
            The first free letter of the status name (first letter preferred),
            falling back to the next unused ``a..z`` when the name offers none.
        """
        import string

        for ch in status.lower():
            if ch.isalpha() and ch not in used:
                return ch
        for ch in string.ascii_lowercase:
            if ch not in used:
                return ch
        # Pathological: more than 26 statuses. Reuse the first letter; the
        # collision is harmless because lookup resolves on first match.
        return status[:1].lower() or "?"

    def on_key(self, event: Any) -> None:
        """Two-key stream dispatcher (see the :data:`KEYMAP` registry).

        When no prefix is armed, a prefix key (``s``/``t``/``c``/``S``) or the
        bare ``?`` arms the matching domain and repaints the hint bar; every
        other key falls through to the flat ``BINDINGS`` (``j``/``k``, ``w``,
        ``/``, ``v`` ...). When a prefix is armed, this key resolves it:
        ``escape`` cancels, ``?`` opens that domain's help, and any other key
        is looked up in the domain's entries and run (unknown keys no-op).
        Note Textual delivers the physical ``?`` as the key ``question_mark``.

        A pending prefix must win over the flat ``BINDINGS`` even when the
        second key is itself a flat binding (``S w`` vs flat ``w``/start-work,
        ``t e`` vs flat ``e``/edit, ``s d`` vs flat ``d``/done). This handler
        runs *before* Textual resolves the key's binding, but merely calling
        :meth:`event.stop` is not enough - ``stop`` halts bubbling, yet the
        key's default binding action still fires afterwards, so ``S w`` would
        both open stats *and* start work. The resolve branch therefore also
        calls :meth:`event.prevent_default` to suppress the colliding flat
        binding, so the second key is handled *only* as the stream action.

        Actions that *open a modal screen* (the help router / per-domain help
        and the global config/stats pop-ups routed through :meth:`_run_entry`)
        are deferred with :meth:`call_after_refresh` so the triggering key
        event has fully settled before the push; pushing a screen synchronously
        from inside the key handler races the event lifecycle and the
        just-pushed screen is torn down again.
        """
        if self._pending is None:
            if event.key in self.keymap:
                self._pending = event.key
                spec = self.keymap[event.key]
                self._hintbar.show_domain(event.key, spec, spec.entries_fn(self))
                self._arm_prefix_timeout()
                event.stop()
            elif event.key == "question_mark":
                # Bare ``?`` opens the top-level help router (handled here, not
                # via a flat binding, so a pending prefix can override it).
                event.stop()
                self.call_after_refresh(self.action_help)
            return
        # A prefix is pending: this key resolves it.
        #
        # A *bare* modifier keypress (``Shift``/``Ctrl``/... tapped on its own,
        # delivered as its own key event on Kitty-protocol terminals) must NOT
        # resolve the prefix - otherwise typing a shifted second key such as
        # ``?`` (which requires pressing ``Shift`` first) would clear the
        # pending prefix on the ``Shift`` event and the following
        # ``question_mark`` would open the top-level help instead of the
        # domain's help. Leave the prefix armed and let the modifier event
        # pass through untouched; the real second key arrives next.
        if event.key in MODIFIER_KEYS:
            return
        domain = self._pending
        self._clear_pending()
        event.stop()
        # Suppress the key's colliding flat binding (e.g. flat ``w`` for ``S
        # w``): this handler runs before the binding fires, but ``stop`` only
        # halts bubbling - without ``prevent_default`` the default binding
        # action would still run and the second key would trigger *both* the
        # stream action and the flat action.
        event.prevent_default()
        if event.key == "escape":
            return
        if event.key == "question_mark":
            self.call_after_refresh(self._open_domain_help, domain)
            return
        entry = self.keymap[domain].lookup(self, event.key)
        if entry is None:
            return
        self._run_entry(domain, entry)

    def _run_entry(self, domain: str, entry: KeyEntry) -> None:
        """Run a resolved stream :class:`KeyEntry`, routed by its ``action`` name.

        Dispatch is keyed off ``entry.action`` (not :attr:`DomainSpec.kind`,
        which is descriptive metadata only), so adding a sub-key that reuses an
        existing ``action_*`` method needs no change here:

        * ``set_status_*`` entries (state domain) and ``cycle_status`` /
          ``cycle_status_prev`` route through :meth:`_bulk_apply` so
          multi-select is honored, resolving the concrete status from the
          registry row (``set_status_<name>`` -> the status string).
        * ``toggle_timer`` (the ``t t`` key) is a per-task mutation like flat
          ``w``, so it also routes through :meth:`_bulk_apply` (spec §8.1).
        * Every other action (the ``t`` domain's remaining task/global actions,
          the ``c``/``S`` global actions, and the ``e`` Edit domain's
          ``edit`` / ``delete_task`` / ``edit_series`` / ``delete_series`` /
          ``series_next`` / ``series_prev`` actions) dispatches to its existing
          ``action_*`` method, which already resolves the single selected task
          or scopes itself appropriately. The ``e`` domain needs no new branch
          here: its actions route straight to ``action_edit`` /
          ``action_delete_task`` / ``action_edit_series`` /
          ``action_delete_series`` / ``action_series_next`` /
          ``action_series_prev``.

        Args:
            domain: The pending prefix key the entry belongs to.
            entry: The resolved :class:`KeyEntry`.
        """
        action = entry.action
        ctx = self.ctx
        if action.startswith("set_status_"):
            status = action[len("set_status_") :].replace("_", "-")
            label = entry.label
            self._bulk_apply(
                lambda task_id: actions.set_status(ctx, self._action_ref(task_id), status),
                lambda task_id, _result: f"{task_id} → {label}.",
                lambda count: f"{count} tasks → {label}.",
            )
            return
        if action == "cycle_status":
            self.action_cycle_status()
            return
        if action == "cycle_status_prev":
            self._bulk_apply(
                lambda task_id: actions.cycle_status_prev(ctx, self._action_ref(task_id)),
                lambda task_id, status: f"{task_id} → {status}.",
                lambda count: f"Cycled {count} tasks.",
            )
            return
        if action == "toggle_timer":
            # Spec §8.1: ``t t`` is a per-task mutation like flat ``w``, so it
            # routes through ``_bulk_apply`` to honor a multi-selection, unlike
            # the single-task ``action_toggle_timer`` reached by no stream key.
            # ``toggle_timer`` returns ``"not_found"`` (truthy) on a bad ref, so
            # map that to ``None`` to keep it out of the affected set.
            self._bulk_apply(
                lambda task_id: (
                    None
                    if (res := actions.toggle_timer(ctx, self._action_ref(task_id))) == "not_found"
                    else res
                ),
                lambda task_id, result: (
                    f"Started focus timer for {task_id}."
                    if result == "started"
                    else f"Stopped focus timer for {task_id}."
                ),
                lambda count: f"Toggled focus timer for {count} tasks.",
            )
            self.refresh_counters()
            return
        # All remaining actions (task_or_global task actions and the global
        # time/config/stats actions) dispatch to their existing action method.
        # Several of these push a modal screen (configure_breaks / work_stats /
        # task_time_stats / manage_work_time / edit_sessions), so defer the
        # call with ``call_after_refresh`` for the same reason the help router
        # is deferred in :meth:`on_key`: pushing a screen synchronously from
        # inside the key handler races the event lifecycle and the just-pushed
        # screen is torn down again.
        method = getattr(self, f"action_{action}", None)
        if method is not None:
            self.call_after_refresh(method)

    def _arm_prefix_timeout(self) -> None:
        """No-op stub (sticky prefix is the v1 default; see spec §11).

        A pending prefix stays armed until a second key, ``escape``, or any
        non-matching key clears it (the hint bar always shows ``Esc:Cancel``),
        so no auto-clear timer is armed. Kept as a seam so a future 1.5s
        auto-clear can be added without changing the dispatcher's shape.
        """
        return None

    def _clear_pending(self) -> None:
        """Clear the pending stream prefix and repaint the hint bar to idle."""
        self._pending = None
        self._hintbar.show_idle(self.keymap)

    def _open_domain_help(self, domain: str) -> None:
        """Open the per-domain help modal for a stream ``domain`` prefix.

        Args:
            domain: The prefix key (``s``/``t``/``c``/``S``).
        """
        spec = self.keymap[domain]
        self.push_screen(self.domain_help_screen_class(domain, spec, spec.entries_fn(self)))

    def _focus_active_view(self) -> None:
        """Give keyboard focus to the active layout's primary widget."""
        view = self._active_view()
        if view is None:
            self.query_one(self.task_list_class).focus()
        else:
            view.focus()

    def apply_layout(self) -> None:
        """Show the active layout's widgets and hide the others.

        The default table layout shows the 3-pane ``#panes`` row (and hides
        the ``#alt-view`` container); the list/kanban/calendar layouts hide
        the panes and show their single view widget inside ``#alt-view``.
        Visibility of each alt-view is driven by the :attr:`ALT_LAYOUTS`
        registry so a new view is handled without a new branch here. The
        ``time`` layout additionally shows the ``#time-pane`` split (day list +
        summary panel) and hides it in every other layout, so the summary
        panel never bleeds into the list/kanban/calendar views.
        """
        is_table = self.layout_view is TuiLayout.TABLE
        is_time = self.layout_view is TuiLayout.TIME
        self.query_one("#panes").display = is_table
        self.query_one("#alt-view").display = not is_table
        self.query_one("#time-pane").display = is_time
        for layout, spec in self.ALT_LAYOUTS.items():
            self.query_one(getattr(self, spec.class_attr)).display = self.layout_view is layout

    def apply_detail_ratio(self) -> None:
        """Resize the table layout's task-list / detail panes from the ratio.

        Applies :attr:`detail_ratio` (an ``"n/d"`` string) to the stacked
        table-layout panes: the lower detail pane is given ``n`` fractional
        height units and the task list the remaining ``d - n`` (so the detail
        pane takes ``n/d`` of the total height), via
        :func:`doxtr_doto.cli.tui.actions.parse_detail_ratio`. Setting the
        ``fr`` heights at runtime (rather than only in the static ``CSS``)
        lets a ratio change from the ``c`` -> ``d`` config pop-up take effect
        immediately, without restarting ``doto tui``.
        """
        from textual.css.scalar import Scalar, Unit

        top_fr, detail_fr = actions.parse_detail_ratio(self.detail_ratio)
        task_list = self.query_one("#task-list")
        task_details = self.query_one("#task-details")
        task_list.styles.height = Scalar(float(top_fr), Unit.FRACTION, Unit.HEIGHT)
        task_details.styles.height = Scalar(float(detail_fr), Unit.FRACTION, Unit.HEIGHT)

    def _cycle_layout(self, step: int) -> None:
        """Advance the task-list layout by ``step`` positions and persist it.

        Shared implementation behind :meth:`action_cycle_layout` (``step=+1``)
        and :meth:`action_cycle_layout_prev` (``step=-1``). Moves ``step``
        places through table -> list -> kanban -> calendar -> time (wrapping in
        either direction), applies the new layout, refreshes the details for
        the newly active view's selection, and persists the choice via
        :func:`doxtr_doto.cli.tui.actions.save_tui_layout` so it is restored on
        the next launch (the "configure", not just toggle, requirement).

        Switching layouts is a *discontinuous* selection change: the newly
        active view may carry a stale scroll offset from a previous visit while
        its selected task sits elsewhere (e.g. the kanban was scrolled to the
        bottom of a long lane and now its selection is a single top-of-lane
        card), so the active alt-view is repositioned via
        :meth:`doxtr_doto.cli.tui.widgets.AltLayoutView.ensure_cursor_visible`
        to guarantee the selected item is in view on the new layout. The
        reposition is deferred with :meth:`call_after_refresh` so it runs after
        the just-shown view's scrollable region is recomputed (a synchronous
        call would be lost to that relayout).
        """
        order = list(TuiLayout)
        nxt = order[(order.index(self.layout_view) + step) % len(order)]
        self.layout_view = nxt
        actions.save_tui_layout(self.ctx, nxt)
        self.apply_layout()
        self._focus_active_view()
        view = self._active_view()
        if view is not None:
            # Defer the reposition until the newly shown view's layout settles:
            # ``apply_layout`` only just toggled the view visible, so its
            # scrollable region is recomputed on the next refresh and a
            # :meth:`~doxtr_doto.cli.tui.widgets.AltLayoutView.ensure_cursor_visible`
            # issued synchronously here would be lost to that relayout (leaving
            # a stale deep offset from a previous visit). ``call_after_refresh``
            # runs it once the region is established, mirroring the help/router
            # deferral pattern used elsewhere.
            self.call_after_refresh(view.ensure_cursor_visible)
        self.refresh_details()
        self.refresh_task_time()
        self.notify(f"Layout: {nxt.value}")

    def action_cycle_layout(self) -> None:
        """Cycle *forward* to the next task-list layout and persist it.

        Thin wrapper for the ``v`` binding; see :meth:`_cycle_layout` for the
        layout ordering and side effects.
        """
        self._cycle_layout(1)

    def action_cycle_layout_prev(self) -> None:
        """Cycle *in reverse* to the previous task-list layout and persist it.

        Thin wrapper for the ``V`` binding and the exact inverse of
        :meth:`action_cycle_layout`; see :meth:`_cycle_layout` for the layout
        ordering and side effects.
        """
        self._cycle_layout(-1)

    def action_activate(self) -> None:
        """Activate the selected task (``Enter``): card viewer popup, or the details pane in the table layout.

        Routing depends on the active layout:

        * **Alternative layouts** (list / kanban / calendar) - open the card
          viewer popup (Feature 3): a modal listing the selected card's full
          detail (same fields as ``doto list -f cards``) with a scrollable
          body. Pressing ``Enter`` again or ``Escape`` closes it; pressing
          ``e`` closes it and opens the existing edit dialog for the same task
          (Feature 4), routed via :meth:`_open_card_viewer`. These layouts
          lack a dedicated details pane, so the popup is the "card view" the
          brief asks for. The active-layout set is identified via
          :meth:`_active_view` (non-None for exactly the
          :attr:`ALT_LAYOUTS`-backed layouts).
        * **Table** - keep the existing behavior: refresh the shared
          :class:`doxtr_doto.cli.tui.widgets.TaskDetails` pane for the selected
          task and move focus to it, mirroring the table layout's
          Tab-to-details flow. The table is the default 3-pane layout with its
          own details pane, so the popup is not used there.

        The selected id comes from whichever layout is active via
        :meth:`_current_selected_id`. When nothing is selectable (e.g. an empty
        store, or a calendar day with no due tasks) ``Enter`` is a harmless
        no-op.
        """
        selected = self._current_selected_id()
        if selected is None:
            return
        if self.layout_view is TuiLayout.TIME:
            self._open_work_time_for_selected_day(selected)
            return
        if self._active_view() is not None:
            self._open_card_viewer(selected)
            return
        self.refresh_details()
        self.refresh_task_time()
        self.query_one(self.task_details_class).focus()

    def _open_work_time_for_selected_day(self, selected: str) -> None:
        """Open the work-time manager for the time view's selected day.

        The time layout's selection id is the highlighted day's ISO date
        (:meth:`doxtr_doto.cli.tui.widgets.TimeView.selected_id`). ``Enter``
        opens the existing :attr:`work_time_screen_class` for that day so
        intervals can be added / edited / deleted; on close the time view and
        the live counters are refreshed so the new totals show immediately.

        Args:
            selected: The selected day's ISO date string.
        """
        from datetime import date as _date

        try:
            day = _date.fromisoformat(selected)
        except ValueError:
            return

        def _done(_result: None) -> None:
            self.refresh_tasks()
            self.refresh_counters()

        self.push_screen(self.work_time_screen_class(self.ctx, day), _done)

    def _default_user(self) -> str:
        """Return the configured default user for the RACI popup field.

        Resolves ``config.user`` first, falling back to
        ``config.default_assignee`` when ``user`` is empty. This is the
        "boring default" the card viewer suppresses from the RACI popup field
        (a RACI role assigned only to this person carries no new information;
        see :meth:`CardViewerScreen.build_extra_field_lines`).

        Returns:
            The default user name, or ``""`` when neither config field is set.
        """
        return self.ctx.config.user or self.ctx.config.default_assignee

    def _open_card_viewer(self, selected: str) -> None:
        """Open the card viewer popup for ``selected`` (Feature 3).

        Used by the list / kanban / calendar layouts' ``Enter`` action.

        Resolves the full task (via :func:`doxtr_doto.cli.tui.actions.find_task`
        against the gathered task set so the display ``id`` is carried) and
        pushes :attr:`card_viewer_screen_class`. When the viewer dismisses with
        the ``"edit"`` sentinel (``e`` pressed inside it) the existing edit
        dialog is opened for the same task (Feature 4) via :meth:`_open_edit`,
        reusing the :func:`doxtr_doto.cli.tui.actions.update_task` write and
        the board refresh rather than duplicating the edit flow. The ``"note"``
        sentinel (``n`` pressed inside it) likewise opens the focused
        body/note editor via :meth:`_open_edit_body`.

        Args:
            selected: The selected task's id.
        """
        task = actions.find_task(self.ctx, self._action_ref(selected))
        if task is None:
            return
        view_task = {"id": selected, **task}

        def _on_close(result: str | None) -> None:
            if result == "edit":
                self._open_edit(selected)
            elif result == "note":
                self._open_edit_body(selected)

        self.push_screen(
            self.card_viewer_screen_class(
                view_task,
                self._default_user(),
                actions.modal_width_percent(self.modal_width_ratio),
            ),
            _on_close,
        )

    def action_layout_move_prev(self) -> None:
        """Move left in the active layout (kanban lane / calendar day).

        In the kanban layout left/right (and ``h``/``l``) now *navigate the
        selection* across the swim lanes - stepping the cursor to the
        adjacent status column without changing any task - so arrows and the
        vim keys stay consistent with the card-navigation role (moving a card
        to another status is now ``Tab``/``Shift+Tab``; see
        :meth:`action_cycle_pane`). In the calendar layout it selects the
        previous day. Other layouts ignore the key.
        """
        self._layout_move(-1)

    def action_layout_move_next(self) -> None:
        """Move right in the active layout (kanban lane / calendar day).

        The mirror of :meth:`action_layout_move_prev` (next swim lane /
        next calendar day).
        """
        self._layout_move(1)

    def _layout_move(self, delta: int) -> None:
        """Dispatch a left/right (``h``/``l`` or arrow) move to the active layout.

        In the kanban layout this navigates the selection across the swim
        lanes (``board.move_column``) so arrows and ``h``/``l`` mirror each
        other; it never moves a card. In the calendar layout it selects the
        adjacent day. Other layouts ignore it.

        Args:
            delta: ``-1`` for left/previous, ``+1`` for right/next.
        """
        if self.layout_view is TuiLayout.KANBAN:
            self._kanban_navigate(delta)
        elif self.layout_view is TuiLayout.CALENDAR:
            calendar = self.query_one(self.calendar_view_class)
            calendar.move_day(delta)
            calendar.rebuild(self._tasks)
            self.refresh_details()

    def _kanban_navigate(self, delta: int) -> None:
        """Navigate the kanban selection across swim lanes (left/right, h/l).

        Relocates the cursor to the adjacent status column via
        :meth:`doxtr_doto.cli.tui.widgets.KanbanView.move_column` so the user
        can select a card in another lane without changing any task. A no-op
        at either edge (no wrap). The details pane auto-refreshes on the
        selection change so navigation keeps it reachable/current.

        A lane switch is discontinuous, so after the rebuild re-renders the
        board the view is repositioned via
        :meth:`doxtr_doto.cli.tui.widgets.AltLayoutView.ensure_cursor_visible`
        to guarantee the selected card is on screen even when the new lane is
        much shorter than the old one. The reposition must run *after*
        :meth:`_rebuild_alt_views`: the rebuild re-renders and re-runs the
        direction-inferring smart scroll (``move_column`` itself only runs the
        continuous :meth:`~doxtr_doto.cli.tui.widgets.AltLayoutView.scroll_to_cursor`,
        which the rebuild would overwrite anyway), so this explicit post-rebuild
        reposition is what actually brings the selected card back into view.

        Args:
            delta: ``-1`` left, ``+1`` right.
        """
        board = self.query_one(self.kanban_view_class)
        if board.move_column(delta):
            self._rebuild_alt_views()
            board.ensure_cursor_visible()
            self.refresh_details()
            self.refresh_task_time()

    def _kanban_statuses(self) -> list[str]:
        """Return the configured status lanes for the kanban rebuild adapter."""
        return list(self.ctx.config.statuses)

    def _kanban_move(self, delta: int) -> None:
        """Move the selected kanban card to the adjacent status column.

        The card-move (status change) is bound to ``Tab``/``Shift+Tab`` in the
        kanban layout (``Tab`` = forward/next lane, ``Shift+Tab`` = back/prev
        lane); see :meth:`action_cycle_pane`. Computes the target status via
        :meth:`doxtr_doto.cli.tui.widgets.KanbanView.move_target_status`, then
        writes it through :func:`doxtr_doto.cli.tui.actions.update_task` (the
        single-task ``doto update`` path) so the status change never
        duplicates business logic. A no-op when the move would leave the
        configured columns (edge or into the ``(other)`` column).

        Args:
            delta: ``-1`` left/back, ``+1`` right/forward.
        """
        board = self.query_one(self.kanban_view_class)
        selected = board.selected_id()
        target = board.move_target_status(delta)
        if selected is None or target is None:
            return
        if actions.update_task(self.ctx, self._action_ref(selected), {"status": target}):
            self.notify(f"{selected} -> {target}.")
            self.refresh_tasks()

    # ------------------------------------------------------------------
    # Daily kickstart nudge (requirement 5)
    # ------------------------------------------------------------------
    def maybe_show_kickstart(self) -> None:
        """Show the once-per-day kickstart nudge if it is due.

        The decision (date dedupe + active-timer suppression) and candidate
        ranking live in :mod:`doxtr_doto.cli.tui.nudge`; this only presents
        the modal and records ``last_prompt_date`` on any dismissal.
        """
        today = nudge.today_iso()
        state = self.ctx.global_store.load()
        focus_active = nudge.has_active_focus(self.ctx)
        if not nudge.should_show_nudge(state.last_prompt_date, focus_active, today):
            return
        candidates = nudge.gather_candidates(self.ctx)
        self.push_screen(
            self.kickstart_screen_class(candidates),
            self._handle_kickstart_choice(candidates),
        )

    def _handle_kickstart_choice(
        self, candidates: list[nudge.Candidate]
    ) -> Callable[[str | None], None]:
        """Build the callback that applies a kickstart choice.

        Args:
            candidates: The candidates offered by the modal.

        Returns:
            A callback accepting the modal's dismissal value.
        """
        by_key = {c.key: c for c in candidates}

        def _apply(choice: str | None) -> None:
            # Record the nudge for today regardless of the choice (including
            # skip / dismissal) so it fires at most once per day.
            nudge.mark_prompted(self.ctx, nudge.today_iso())
            if choice in by_key:
                self._start_candidate(by_key[choice])
            elif choice == "work":
                actions.clock_in_work(self.ctx)
                self.notify("Clocked in to general work.")
                self.refresh_counters()
            elif choice == "search":
                self.action_filter()

        return _apply

    def _start_candidate(self, candidate: nudge.Candidate) -> None:
        """Start a focus timer for a chosen kickstart candidate.

        Args:
            candidate: The candidate task to start.
        """
        result = actions.toggle_timer(self.ctx, candidate.ref)
        if result == "started":
            self.notify(f"Started focus timer for {candidate.ref}.")
        elif result == "stopped":
            self.notify(f"Stopped focus timer for {candidate.ref}.")
        else:
            self.notify(f"Could not resolve {candidate.ref}.", severity="error")
            return
        self.refresh_tasks()
        self.refresh_counters()

    # ------------------------------------------------------------------
    # Pane / view model refresh
    # ------------------------------------------------------------------
    def refresh_repos(self) -> None:
        """Rebuild the repo tree from the cached registry.

        The currently selected repositories
        (:attr:`view_prefs`'s ``repo_filter``) are passed through so the tree
        marks each selected repo leaf.
        """
        tree = self.query_one(self.repo_tree_class)
        state = self.ctx.global_store.load()
        tree.rebuild(
            data.list_repos(self.ctx),
            list(state.favorites),
            self.scope,
            data.current_repo_name(self.ctx),
            set(self.view_prefs.repo_filter),
        )

    def _visible_tasks(self) -> list[dict[str, Any]]:
        """Return the gathered tasks after filtering, sorting, and active-pin.

        The composition order is the one the brief requires, each step a
        separate overridable call:

            gather -> text ``filter_term`` -> apply :class:`ViewPrefs` filters
                  -> apply :class:`ViewPrefs` sort -> pin active task(s) to top

        The text filter (:attr:`filter_term`) is applied first
        (:meth:`_apply_text_filter`), then the configured filter/sort
        preferences and the active-pin via
        :func:`doxtr_doto.cli.tui.filtersort.apply_view_prefs` (Features A/C).
        The three pipeline steps are passed as the app's overridable
        ``staticmethod`` seams (:attr:`apply_filters`, :attr:`apply_sort`,
        :attr:`pin_active_first`), so a child theme swaps one step by setting
        one attribute without re-implementing this method. The active
        (time-recorded) task is always pinned last so it stays on top
        regardless of the sort.

        The repository filter is scope-gated here: in LOCAL scope the gathered
        set is already the single current repository, so the repo filter is
        suppressed (passed as an empty tuple) before filtering. This enforces
        the documented contract that LOCAL always shows the current repo and
        ignores any persisted ``repo_filter`` - otherwise a selection made in
        GLOBAL for a *different* repo would silently empty the LOCAL list.

        Returns:
            The task dicts matching the text term and the configured
            filter/sort prefs, with the active task(s) pinned to the top.
        """
        from doxtr_doto.cli.tui.filtersort import apply_view_prefs

        tasks = data.gather_tasks(self.ctx, self.scope)
        # Build the ``next``-scorer dependency map from the full gathered set
        # (before the free-text filter narrows it) so a blocking dependency
        # hidden by an active ``/`` filter is still visible to the scorer and
        # cannot flip a task to "unblocked" in the recommended-next order.
        all_tasks = {str(t.get("id", "")): t for t in tasks}
        tasks = self._apply_text_filter(tasks)
        prefs = self._scoped_view_prefs()
        return apply_view_prefs(
            tasks,
            prefs,
            all_tasks=all_tasks,
            apply_filters_fn=self.apply_filters,
            apply_sort_fn=self.apply_sort,
            pin_active_first_fn=self.pin_active_first,
        )

    def _scoped_view_prefs(self) -> ViewPrefs:
        """Return :attr:`view_prefs` with the repo filter gated by scope.

        The repo filter is only meaningful in
        :data:`doxtr_doto.cli.display.DisplayScope.GLOBAL`, where several
        repositories' tasks are aggregated. In LOCAL scope the gathered set is
        already the single current repository, so a persisted ``repo_filter``
        (set while in GLOBAL, possibly naming a *different* repo) must be
        ignored - applying it could silently empty the list. This returns the
        prefs unchanged in GLOBAL and a copy with ``repo_filter`` cleared in
        LOCAL, leaving the persisted selection intact for when the user
        switches back to GLOBAL.

        Returns:
            The view prefs to filter with for the current scope.
        """
        if self.scope is DisplayScope.LOCAL and self.view_prefs.repo_filter:
            return replace(self.view_prefs, repo_filter=())
        return self.view_prefs

    def _apply_text_filter(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return ``tasks`` matching the free-text :attr:`filter_term`.

        The first (overridable) step of :meth:`_visible_tasks`: a
        case-insensitive substring match of :attr:`filter_term` against each
        task's id, title, and tags. Returns ``tasks`` unchanged when the term
        is empty.

        Args:
            tasks: The gathered task dicts.

        Returns:
            The matching subset (all tasks when the term is empty).
        """
        if not self.filter_term:
            return tasks
        term = self.filter_term.lower()
        matched: list[dict[str, Any]] = []
        for task in tasks:
            haystack = " ".join(
                [
                    str(task.get("id", "")),
                    str(task.get("title", "")),
                    " ".join(task.get("tags") or []),
                ]
            ).lower()
            if term in haystack:
                matched.append(task)
        return matched

    def refresh_tasks(self) -> None:
        """Rebuild the active layout's task view and refresh the details pane."""
        self._tasks = self._visible_tasks()
        table = self.query_one(self.task_list_class)
        table.rebuild(self._tasks, self._collapsed_ids)
        self._rebuild_alt_views()
        self.refresh_details()

    def _rebuild_alt_views(self) -> None:
        """Rebuild the alternative layout views from the current task set.

        The list/kanban/calendar widgets are always kept in sync (cheap,
        pure-markup rebuilds) so switching layouts with ``v`` shows current
        data immediately. Only the active one is visible (see
        :meth:`apply_layout`). Each view is rebuilt through its
        :attr:`ALT_LAYOUTS` adapter, which absorbs per-view ``rebuild``
        signature differences (kanban also needs the configured statuses).
        """
        for spec in self.ALT_LAYOUTS.values():
            spec.rebuild(self)

    def _rebuild_time_layout(self) -> None:
        """Rebuild the ``time`` layout's day list and summary panel together.

        Both the :attr:`time_view_class` day list and the
        :attr:`work_time_summary_class` week/month/year panel are driven from
        the *same* work-clock intervals and breaks, so they stay in sync (and
        the summary refreshes whenever intervals change, e.g. after the
        work-time manager modal closes via :meth:`refresh_tasks`). This is the
        TIME row's :attr:`ALT_LAYOUTS` rebuild adapter.
        """
        state = self.ctx.global_store.load()
        worklogs = state.work_clock.worklogs
        breaks = list(state.breaks)
        self.query_one(self.time_view_class).rebuild(worklogs, breaks)
        self.query_one(self.work_time_summary_class).rebuild(
            worklogs, breaks, workweek_days=list(state.workweek_days)
        )

    def refresh_details(self) -> None:
        """Refresh the details pane for the current selection.

        Resolves the selection against the already-gathered :attr:`_tasks`
        rather than reloading it from the store: the gathered dict carries the
        display ``id`` (namespaced in global scope) plus the TUI-only keys,
        whereas the raw store task
        (:func:`doxtr_doto.cli.tui.actions.find_task` ->
        ``JsonTaskStore.get_task``) has no ``id`` key at all - so rendering it
        showed an empty id in the details pane. ``find_task`` remains the
        fallback for a selection that is not in the current (possibly
        filtered) task set, with the resolved id injected so the id still
        shows.
        """
        details = self.query_one(self.task_details_class)
        selected = self._current_selected_id()
        task: dict[str, Any] | None = None
        if selected is not None:
            task = next((t for t in self._tasks if t.get("id") == selected), None)
            if task is None:
                found = actions.find_task(self.ctx, self._action_ref(selected))
                if found is not None:
                    # The store task has no id key; inject the resolved id so
                    # the details pane still shows it.
                    task = {"id": selected, **found}
        details.update_task(task, data.session_intervals(task))

    def refresh_counters(self) -> None:
        """Refresh the live status-line counters and the task-time display.

        Driven by a recurring :meth:`set_interval` timer, so it can fire while
        the app is still mounting or already tearing down (or while a modal is
        pushed). In those windows the status line may not be queryable yet /
        anymore; a missing widget is a benign no-op rather than an error.

        A single :func:`data.live_counters` call supplies both the status-line
        counters and the current work-session seconds, so the timer path never
        loads the store twice. The terminal tab title is re-asserted here too
        (see :meth:`_set_terminal_title`) so terminals that reset the label to
        the process name keep showing the configured title.
        """
        # Re-assert the terminal tab title: some terminals (e.g. the VS Code
        # integrated terminal) reset the label to the foreground process name
        # (``python3``) after process detection, clobbering a title set only
        # once at mount. Re-emitting the identical OSC 0 sequence is a no-op
        # visually and keeps the configured label stable.
        self._set_terminal_title()
        work_today, work_running, session_seconds, focus_seconds = data.live_counters(self.ctx)
        try:
            status_line = self.query_one(self.status_line_class)
        except NoMatches:
            pass
        else:
            status_line.update_counters(work_today, work_running, focus_seconds)
        self.refresh_task_time(work_today, session_seconds, work_running)

    def refresh_task_time(
        self,
        work_today_seconds: int | None = None,
        session_seconds: int | None = None,
        session_running: bool | None = None,
    ) -> None:
        """Refresh the top-right day's-work + current-task elapsed display.

        The first value is the accumulated *total work time for the whole day*
        (summed across all of today's work-clock intervals), with the *current
        work session* - the elapsed time of the single currently-open
        work-clock interval - shown in parentheses after it. The *current
        task* is the one highlighted in the task list; its total time is summed
        across all worklogs via
        :func:`doxtr_doto.cli.tui.data.task_total_seconds`. Shares the same
        benign no-op behavior as :meth:`refresh_counters` when the widget is
        not currently mounted.

        Args:
            work_today_seconds: Precomputed accumulated work seconds for the
                whole day, to avoid a second :func:`data.live_counters` store
                load; recomputed via :func:`data.live_counters` when None.
            session_seconds: Precomputed current work-session seconds to avoid
                a second store load; recomputed when None.
            session_running: Precomputed flag for whether a work session is
                open; recomputed when None.
        """
        try:
            time_line = self.query_one(self.task_time_line_class)
        except NoMatches:
            return
        if work_today_seconds is None or session_seconds is None or session_running is None:
            work_today_seconds, work_running, session_seconds, _focus = data.live_counters(self.ctx)
            session_running = work_running
        selected = self._current_selected_id()
        task = actions.find_task(self.ctx, self._action_ref(selected)) if selected else None
        time_line.update_times(
            work_today_seconds,
            session_seconds,
            session_running,
            selected,
            data.task_total_seconds(task),
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_cursor_down(self) -> None:
        """Move the active layout's cursor down.

        For the table layout the cursor move posts a
        :class:`DataTable.RowHighlighted` message, which
        :meth:`on_data_table_row_highlighted` handles by refreshing the
        details pane and task-time display, so we do not refresh explicitly
        there. The list/kanban/calendar views have no such message, so they
        move their own cursor and refresh here.
        """
        self._move_cursor(1)

    def action_cursor_up(self) -> None:
        """Move the active layout's cursor up (see :meth:`action_cursor_down`)."""
        self._move_cursor(-1)

    def _move_cursor(self, delta: int) -> None:
        """Move the active layout's cursor by ``delta`` rows.

        Args:
            delta: Rows to move (negative moves up).
        """
        if self.layout_view is TuiLayout.TABLE:
            table = self.query_one(self.task_list_class)
            if delta > 0:
                table.action_cursor_down()
            else:
                table.action_cursor_up()
            return
        view = self._active_view()
        if view is None:
            return
        view.move_cursor(delta)
        self._rebuild_alt_views()
        self.refresh_details()
        self.refresh_task_time()

    def action_cursor_top(self) -> None:
        """Jump the active layout's cursor to the first entry (``Shift+Up``).

        The jump-to-edge counterpart of :meth:`action_cursor_up`: instead of
        stepping one row it snaps the cursor to the top of the current list.
        Like :meth:`action_cursor_down`, the table layout's cursor move posts a
        :class:`DataTable.RowHighlighted` message (handled by
        :meth:`on_data_table_row_highlighted`), while the alt views move their
        own cursor and refresh here; both paths funnel through
        :meth:`_jump_cursor`.
        """
        self._jump_cursor(False)

    def action_cursor_bottom(self) -> None:
        """Jump the active layout's cursor to the last entry (``Shift+Down``).

        The jump-to-edge counterpart of :meth:`action_cursor_down` (see
        :meth:`action_cursor_top`).
        """
        self._jump_cursor(True)

    def _jump_cursor(self, to_bottom: bool) -> None:
        """Jump the active layout's cursor to the first or last entry.

        The jump-to-edge sibling of :meth:`_move_cursor`: it mirrors that
        method's TABLE-vs-alt-view dispatch exactly so the two navigation
        paths stay in lockstep.

        * **Table** - move the :class:`~textual.widgets.DataTable` row cursor
          to row ``0`` (top) or the last row (bottom) via
          :meth:`~textual.widgets.DataTable.move_cursor`, guarding an empty
          table. The move posts a
          :class:`~textual.widgets.DataTable.RowHighlighted` message that
          :meth:`on_data_table_row_highlighted` turns into the details /
          task-time refresh, so (as in :meth:`_move_cursor`) no explicit
          refresh is needed here.
        * **Alt views** - delegate to the active view's overridable
          :meth:`~doxtr_doto.cli.tui.widgets.AltLayoutView.move_cursor_to_edge`
          seam, then rebuild / refresh exactly as :meth:`_move_cursor` does.

        Args:
            to_bottom: Jump to the last entry when True, the first when False.
        """
        if self.layout_view is TuiLayout.TABLE:
            table = self.query_one(self.task_list_class)
            if table.row_count == 0:
                return
            table.move_cursor(row=table.row_count - 1 if to_bottom else 0)
            return
        view = self._active_view()
        if view is None:
            return
        view.move_cursor_to_edge(to_bottom)
        self._rebuild_alt_views()
        self.refresh_details()
        self.refresh_task_time()

    def action_cycle_pane(self) -> None:
        """Cycle forward across the panes / move a kanban card (``Tab``).

        In the table layout this cycles the three structural panes
        (repo tree -> task list -> details -> repo tree).

        In the kanban layout ``Tab`` *moves the selected card* one lane
        forward (to the next status column) - the status change that the
        left/right arrows used to perform. The move is routed through
        :meth:`_kanban_move` /
        :func:`doxtr_doto.cli.tui.actions.update_task` so it never duplicates
        business logic. It is a no-op when the card is already in the last
        real column or the move would land in the ``(other)`` column (see
        :meth:`doxtr_doto.cli.tui.widgets.KanbanView.move_target_status`): the
        board does not wrap or crash. Navigating the *selection* across lanes
        (without moving a card) is on the left/right arrows and ``h``/``l``
        (:meth:`action_layout_move_next` /
        :meth:`action_layout_move_prev`); the details pane stays reachable
        because it auto-refreshes on every selection change.

        The calendar layout cycles through the view's three focus regions and
        the details pane (grid -> Due list -> No-due list -> details -> grid),
        so ``Tab`` walks from a selected day into its due tasks and the
        undated bucket (where ``e`` / ``Enter`` / done act on the highlighted
        task) and then into the details pane. Dispatched via the registry's
        ``tab_action`` (:meth:`_cycle_calendar_region`), not a hard-coded
        branch.

        The plain list layout keeps focus on its single view (there is no
        second pane worth cycling into for a one-line-per-task list), so Tab
        is a no-op there beyond re-focusing the view.

        This is the forward direction; :meth:`action_cycle_pane_reverse`
        (``Shift+Tab``) walks the exact same cycle in reverse (and moves a
        kanban card one lane *back*). Both delegate to :meth:`_cycle_pane`
        with a signed direction so the forward and reverse paths share one
        implementation per layout.
        """
        self._cycle_pane(1)

    def action_cycle_pane_reverse(self) -> None:
        """Cycle backward across the panes / move a kanban card back.

        Bound to ``Shift+Tab``, this walks the *exact reverse* of the forward
        :meth:`action_cycle_pane` cycle:

        * **Table** - repo tree -> details -> task list -> repo tree (the
          reverse of forward's repo tree -> task list -> details).
        * **Kanban** - *moves the selected card* one lane *back* (to the
          previous status column), the mirror of ``Tab`` moving it forward. A
          no-op from the first real column or into the ``(other)`` column (no
          wrap/crash).
        * **Calendar** - the region/details cycle walked in reverse
          (grid <- Due <- No-due <- details), via :meth:`_cycle_calendar_region`.
        * **List** - a no-op beyond re-focusing the single view, like forward.

        Delegates to :meth:`_cycle_pane` with ``direction=-1`` so the reverse
        path reuses the forward logic rather than duplicating it.
        """
        self._cycle_pane(-1)

    def _cycle_pane(self, direction: int) -> None:
        """Cycle panes for the active layout in the given direction.

        The shared core of :meth:`action_cycle_pane` (``direction=1``) and
        :meth:`action_cycle_pane_reverse` (``direction=-1``): it routes to the
        per-layout helper, each of which honors ``direction`` so the reverse
        cycle is the exact mirror of the forward one. The public forward
        action's behavior is unchanged (it still calls this with
        ``direction=1``).

        Args:
            direction: ``+1`` to cycle forward, ``-1`` to cycle in reverse.
        """
        if self.layout_view is TuiLayout.TABLE:
            order: list[type[Any]] = [
                self.repo_tree_class,
                self.task_list_class,
                self.task_details_class,
            ]
            self._focus_next_in_cycle(order, direction)
            return
        spec = self.ALT_LAYOUTS.get(self.layout_view)
        if spec is not None and spec.tab_action is not None:
            # The view rebinds Tab/Shift+Tab to its own action (e.g. kanban
            # moves the selected card one lane forward/back). Dispatched via
            # the registry so key->action policy stays data-driven, not a
            # hard-coded per-layout branch.
            spec.tab_action(self, direction)
            return
        if spec is not None and spec.cycles_details:
            self._cycle_alt_view_details(direction)
            return
        # Layouts whose spec does not opt into the details cycle (the plain
        # list layout) have a single focusable view; keep focus on it.
        self._focus_active_view()

    def _focus_next_in_cycle(self, order: list[type[Any]], direction: int = 1) -> None:
        """Focus the widget adjacent to the focused one in ``order`` (wrapping).

        Args:
            order: The widget classes to cycle through, in order. For the
                forward direction the first is focused when nothing in
                ``order`` currently holds focus; for the reverse direction the
                last is focused in that case (so the reverse cycle is the exact
                mirror of the forward one).
            direction: ``+1`` to focus the next widget, ``-1`` to focus the
                previous one. Defaults to forward so existing callers are
                unchanged.
        """
        focused = self.focused
        current = -1
        for index, cls in enumerate(order):
            if isinstance(focused, cls):
                current = index
                break
        if current == -1 and direction < 0:
            # Nothing focused yet: the reverse cycle enters at the last pane
            # (the mirror of the forward cycle entering at the first).
            nxt = order[-1]
        else:
            nxt = order[(current + direction) % len(order)]
        self.query_one(nxt).focus()

    def _cycle_alt_view_details(self, direction: int = 1) -> None:
        """Toggle focus between the active alt-view and the details pane.

        The deterministic two-step cycle for any alt-view whose registry row
        sets ``cycles_details=True``: when the alt-view (or anything that is
        not the details pane) has focus, Tab moves to :class:`TaskDetails`
        after refreshing it for the current selection; when details already
        has focus, Tab moves back to the alt-view. This mirrors the table
        layout's Tab-to-details flow with a single alt-view pane.

        No current layout opts into this (the kanban and calendar layouts set
        a ``tab_action`` instead), but the generic ``cycles_details`` path is
        kept so a future alt-view with a plain view <-> details relationship
        can opt in with a one-line registry flag rather than a new branch.

        The toggle is symmetric, so ``direction`` does not change which of the
        two states is next; it is accepted (and ignored beyond that) so the
        reverse cycle (``Shift+Tab``) routes through the same helper as the
        forward cycle, keeping the reverse-aware dispatch in :meth:`_cycle_pane`
        explicit and uniform across every layout.

        Args:
            direction: ``+1`` forward, ``-1`` reverse. The view <-> details
                toggle is symmetric, so both move to the opposite pane.
        """
        del direction  # The two-state toggle is symmetric in either direction.
        details = self.query_one(self.task_details_class)
        if isinstance(self.focused, self.task_details_class):
            self._focus_active_view()
            return
        # Entering the details pane: show the current selection there first.
        self.refresh_details()
        self.refresh_task_time()
        details.focus()

    def _cycle_calendar_region(self, direction: int) -> None:
        """Cycle the calendar's focus through its regions and details pane.

        The calendar layout's ``Tab``/``Shift+Tab`` handler (its
        :attr:`AltLayoutSpec.tab_action`). The calendar view has three
        internal focus regions - the month grid, the "Due" list, and the
        "No due date" list (see
        :class:`doxtr_doto.cli.tui.widgets.CalendarView`) - plus the shared
        details pane, which together form one ``Tab`` cycle:

            grid -> Due -> No-due -> details -> grid

        ``Shift+Tab`` walks the exact reverse. Advancing the view's region is
        delegated to :meth:`doxtr_doto.cli.tui.widgets.CalendarView.cycle_region`,
        which returns ``0`` while it stays within the grid/Due/No-due regions
        and the signed ``direction`` when it steps off either end; that
        off-end step is where focus moves *into* the details pane. When the
        details pane already has focus, the next step re-enters the view at
        the grid (forward) or the No-due list (reverse) so the cycle is a
        clean loop in both directions.

        On any region change the view is re-rendered (so the newly focused
        list's cursor highlight shows) and the details pane / task-time
        display are refreshed for the new selection, matching the other
        layouts' Tab-into-details behavior.

        Args:
            direction: ``+1`` for ``Tab`` (forward), ``-1`` for ``Shift+Tab``.
        """
        calendar = self.query_one(self.calendar_view_class)
        details = self.query_one(self.task_details_class)
        if isinstance(self.focused, self.task_details_class):
            # Leaving the details pane: forward loops back to the grid,
            # reverse re-enters the view at its last region (No-due).
            calendar.set_focus_region(
                calendar.REGION_GRID if direction > 0 else calendar.REGION_NO_DUE
            )
            self._refresh_calendar_focus()
            calendar.focus()
            return
        stepped_off = calendar.cycle_region(direction)
        if stepped_off != 0:
            # The view ran off the end of its regions: hand focus to the
            # details pane (refreshed for the current selection first),
            # mirroring every other layout's Tab-to-details step.
            self.refresh_details()
            self.refresh_task_time()
            details.focus()
            return
        # Still within the view's regions: re-render so the new region's
        # cursor highlight shows and refresh the selection-driven panes.
        self._refresh_calendar_focus()
        calendar.focus()

    def _refresh_calendar_focus(self) -> None:
        """Re-render the calendar and refresh the selection-driven panes.

        Shared by :meth:`_cycle_calendar_region` (and any future calendar
        selection change): rebuilds the alt-views (so the active
        region's cursor highlight re-renders) and refreshes the details /
        task-time panes for the new selection.
        """
        self._rebuild_alt_views()
        self.refresh_details()
        self.refresh_task_time()

    def on_data_table_row_highlighted(self, event: Any) -> None:
        """Refresh details and the task-time display when the row changes."""
        self.refresh_details()
        self.refresh_task_time()

    def on_data_table_row_selected(self, event: Any) -> None:
        """Reveal the selected row's details on ``Enter`` in the table layout.

        The table layout's :class:`~textual.widgets.DataTable` consumes
        ``Enter`` with its own ``select_cursor`` binding (posting
        :class:`~textual.widgets.DataTable.RowSelected`) before the app's
        ``enter`` binding fires, so the Enter-to-detail reveal for the table
        layout is wired here rather than through :meth:`action_activate`
        (which handles the list/kanban/calendar layouts). It refreshes the
        shared details pane for the current row and focuses it, mirroring
        :meth:`action_activate`.
        """
        if self._current_selected_id() is None:
            return
        self.refresh_details()
        self.refresh_task_time()
        self.query_one(self.task_details_class).focus()

    def on_tree_node_selected(self, event: Tree.NodeSelected[None]) -> None:
        """Toggle a repository in the repo filter when its tree leaf is selected.

        The repo tree's :class:`~textual.widgets.Tree` posts ``NodeSelected``
        when a leaf is activated. Repository leaves carry their bare repo name
        on ``node.data`` (set by
        :meth:`doxtr_doto.cli.tui.widgets.RepoTree.rebuild`), so selecting one
        toggles that repo in :attr:`view_prefs`'s ``repo_filter``, persists the
        change via :func:`doxtr_doto.cli.tui.actions.save_view_prefs`, and
        refreshes the task list and the tree (so the selection marker updates).
        Nodes without a repo-name ``data`` (the root, section headers, the
        favorites / placeholder leaves) are ignored.

        The repo filter is only meaningful in GLOBAL scope, so in LOCAL scope
        this is a no-op: toggling would persist a selection the LOCAL view
        ignores (see :meth:`_scoped_view_prefs`), which would be confusing.
        """
        if self.scope is DisplayScope.LOCAL:
            return
        repo = getattr(event.node, "data", None)
        if not isinstance(repo, str):
            return
        self.toggle_repo_filter(repo)

    def toggle_repo_filter(self, repo: str) -> None:
        """Toggle ``repo`` in the repo filter, then persist and refresh.

        The overridable behavior behind :meth:`on_tree_node_selected`: flips
        ``repo``'s membership in :attr:`view_prefs`'s ``repo_filter``, persists
        the change via
        :func:`doxtr_doto.cli.tui.actions.save_view_prefs`, and refreshes both
        the task list and the tree (so the selection marker updates). Factored
        out of the event handler so a child theme can change tree-selection
        semantics (e.g. single-select) without re-reading ``event.node`` plumbing.

        Args:
            repo: The repository name to toggle in the filter.
        """
        current = list(self.view_prefs.repo_filter)
        if repo in current:
            current.remove(repo)
        else:
            current.append(repo)
        self.view_prefs = replace(self.view_prefs, repo_filter=tuple(current))
        actions.save_view_prefs(self.ctx, self.view_prefs)
        self.refresh_tasks()
        self.refresh_repos()

    # ------------------------------------------------------------------
    # Mutations (all routed through actions.py / CLI verb functions)
    # ------------------------------------------------------------------
    def action_select(self) -> None:
        """Toggle tree expansion on a parent row, else multi-select the task.

        Space is the tree-expand toggle *and* the multi-select toggle, split by
        the cursor row's shape (mirroring how tree UIs - including the repo
        explorer - treat Space on a branch vs a leaf): when the cursor row has
        children (is an expandable parent) Space toggles whether its sub-tasks
        are shown (flipping the row's membership in :attr:`_collapsed_ids` and
        refreshing); when it is a leaf Space keeps its multi-select behaviour
        so parenting and the ``d``/``D`` bulk actions still work. Multi-select
        is a table-layout affordance; in the single-selection list/kanban/
        calendar layouts Space is a no-op.
        """
        if self.layout_view is not TuiLayout.TABLE:
            return
        table = self.query_one(self.task_list_class)
        if table.cursor_has_children():
            task_id = table.selected_id()
            if task_id is not None:
                # Default-expanded: membership in _collapsed_ids means hidden,
                # so toggling membership flips show/hide of the sub-tasks.
                if task_id in self._collapsed_ids:
                    self._collapsed_ids.discard(task_id)
                else:
                    self._collapsed_ids.add(task_id)
                self.refresh_tasks()
            return
        table.toggle_selected()
        self.refresh_tasks()

    def _bulk_target_ids(self) -> list[str]:
        """Resolve the current bulk-action target ids for the active layout.

        The shared target-resolution used by :meth:`_bulk_apply` and
        :meth:`action_set_parent`: in the table layout the multi-selection
        (when non-empty, else the single cursor row) via
        :meth:`~doxtr_doto.cli.tui.widgets.TaskList.target_ids`; in the
        single-selection layouts (list/kanban/calendar/time) just the single
        selected id. Empty when nothing is selectable.

        Returns:
            The display ids a bulk action should operate on.
        """
        if self.layout_view is TuiLayout.TABLE:
            return self.query_one(self.task_list_class).target_ids()
        selected = self._current_selected_id()
        return [selected] if selected is not None else []

    def _bulk_apply(
        self,
        apply: Any,
        singular: Any,
        plural: Any,
    ) -> None:
        """Run a per-task mutation over the current bulk-action targets.

        Resolves the target ids (multi-selection when non-empty, else the
        single cursor task), applies ``apply`` to each, clears the selection,
        notifies the user, and refreshes the task list. Keeps the shared
        scaffolding of ``action_done`` / ``action_cycle_status`` in one place.

        Args:
            apply: Callable taking a task id and returning the per-task result
                (truthy / non-None means the task was affected). For the
                status cycle this is the new status string; for completion a
                bool.
            singular: Callable ``(task_id, result) -> str`` building the notify
                message when exactly one task was affected.
            plural: Callable ``(count) -> str`` building the notify message
                when more than one task was affected.
        """
        table = self.query_one(self.task_list_class)
        targets = self._bulk_target_ids()
        if not targets:
            return
        affected: list[tuple[str, Any]] = []
        for task_id in targets:
            result = apply(task_id)
            if result is not None and result is not False:
                affected.append((task_id, result))
        table.clear_selection()
        if len(affected) == 1:
            task_id, result = affected[0]
            self.notify(singular(task_id, result))
        elif affected:
            self.notify(plural(len(affected)))
        self.refresh_tasks()

    def action_done(self) -> None:
        """Mark the target task(s) done.

        Operates on the multi-selection when it is non-empty, otherwise on the
        single cursor task. Clears the selection afterwards.
        """
        self._bulk_apply(
            lambda task_id: actions.complete_task(self.ctx, self._action_ref(task_id)),
            lambda task_id, _result: f"Completed {task_id}.",
            lambda count: f"Completed {count} tasks.",
        )

    def action_cycle_status(self) -> None:
        """Advance the target task(s) to the next status in the cycle.

        Operates on the multi-selection when it is non-empty, otherwise on the
        single cursor task. Clears the selection afterwards.
        """
        self._bulk_apply(
            lambda task_id: actions.cycle_status(self.ctx, self._action_ref(task_id)),
            lambda task_id, status: f"{task_id} → {status}.",
            lambda count: f"Cycled {count} tasks.",
        )

    def action_set_parent(self) -> None:
        """Attach the target task(s) to a PARENT task picked from a pop-up.

        The ``e P`` Edit-domain action. Resolves the child targets with the
        SAME bulk-target logic as :meth:`_bulk_apply` (:meth:`_bulk_target_ids`:
        the multi-selection when non-empty, else the single cursor task), so
        whatever is currently selected becomes the set of CHILDREN. Opens
        :attr:`set_parent_screen_class` listing every OTHER visible task as a
        candidate parent - the children themselves are excluded - pre-seeded
        with the remembered last parent (:attr:`_last_parent_id`) so assigning
        several tasks to the same parent is quick.

        On confirm the chosen parent is applied to every child via
        :func:`doxtr_doto.cli.tui.actions.set_parent`, which rejects
        self-parenting / cycles (:func:`~doxtr_doto.sync.json_store.would_create_cycle`)
        and cross-repo parents per child; rejected children are skipped and
        counted into a trailing notice. The remembered parent is updated and
        the board refreshed, mirroring the singular/plural notify shape of
        :meth:`_bulk_apply`. The list also offers a leading "(no parent)" entry
        (value :data:`~doxtr_doto.cli.tui.actions.CLEAR_PARENT`) that *removes*
        the parent from every target, making them top-level again. ``Escape``
        cancels without changes.
        """
        targets = self._bulk_target_ids()
        if not targets:
            return
        target_set = set(targets)
        # Candidate parents: every OTHER visible task (exclude the children
        # being parented and, implicitly, each child's own row). ``value`` is
        # the action ref the parent resolves through; ``label`` is the display
        # ``id  title`` the user reads. A leading "(no parent)" entry clears the
        # parent link instead of attaching one.
        candidates: list[tuple[str, str]] = [("(no parent)", actions.CLEAR_PARENT)]
        for task in self._tasks:
            display_id = str(task.get("id", ""))
            if not display_id or display_id in target_set:
                continue
            title = str(task.get("title", ""))
            label = f"{display_id}  {title}" if title else display_id
            candidates.append((label, self._action_ref(display_id)))
        # ``candidates`` always has the "(no parent)" row, so there is always
        # at least the clear option available (even with no other tasks).

        def _chosen(parent_ref: str | None) -> None:
            if parent_ref is None:
                return
            clearing = parent_ref == actions.CLEAR_PARENT
            affected: list[str] = []
            skipped = 0
            for child_id in targets:
                result = actions.set_parent(self.ctx, self._action_ref(child_id), parent_ref)
                if result in (SetParentResult.OK, SetParentResult.CLEARED):
                    affected.append(child_id)
                else:
                    skipped += 1
            table = self.query_one(self.task_list_class)
            table.clear_selection()
            if affected and not clearing:
                # Remember the chosen parent for the next open so the picker
                # pre-selects it (session-scoped; see ``_last_parent_id``).
                # Clearing is never remembered as a "last parent".
                self._last_parent_id = parent_ref
            suffix = f" ({skipped} skipped)" if skipped else ""
            if clearing:
                if len(affected) == 1:
                    self.notify(f"Removed parent of {affected[0]}.{suffix}")
                elif affected:
                    self.notify(f"Removed parent of {len(affected)} tasks.{suffix}")
                else:
                    self.notify("No parent to remove.")
            elif len(affected) == 1:
                self.notify(f"Set parent of {affected[0]} to {parent_ref}.{suffix}")
            elif affected:
                self.notify(f"Set parent of {len(affected)} tasks to {parent_ref}.{suffix}")
            elif skipped:
                self.notify(
                    "Could not set parent (self/cycle or cross-repo).",
                    severity="warning",
                )
            self.refresh_tasks()

        self.push_screen(
            self.set_parent_screen_class(candidates, default=self._last_parent_id),
            _chosen,
        )

    def action_edit(self) -> None:
        """Open the edit modal for the current task and apply the result."""
        selected = self._current_selected_id()
        if not selected:
            return
        self._open_edit(selected)

    def action_edit_series(self) -> None:
        """Edit the selected occurrence's series from this occurrence forward.

        The ``e E`` Edit-domain action (shown only for a series occurrence).
        Resolves the selected task, reads its ``series_id`` (notifies and
        returns when absent -- defensive; the menu already hides it), and
        captures the task's due DATE (time stripped) as the forward-only
        anchor. Pushes :attr:`edit_series_screen_class` pre-populated from the
        stored series; on submit the validated pattern/title are handed to
        :func:`doxtr_doto.cli.tui.actions.update_series` -- the SAME reusable
        function the CLI ``doto series update`` path uses -- then the store is
        reloaded and the board/details refreshed. Modeled on :meth:`_open_edit`
        + :meth:`action_add_series`.
        """
        from doxtr_doto.cli.recurrence import parse_recurrence

        selected = self._current_selected_id()
        if not selected:
            return
        ref = self._action_ref(selected)
        task = actions.find_task(self.ctx, ref)
        if task is None:
            return
        series_id = task.get("series_id")
        if not isinstance(series_id, str) or not series_id:
            self.notify("Selected task is not part of a series.")
            return
        anchor = actions.occurrence_date(task.get("due"))
        if anchor is None:
            self.notify("Selected occurrence has no due date to anchor on.", severity="error")
            return
        series_data = self.ctx.store.get_series(series_id)
        if series_data is None:
            self.notify(f"Series {series_id} not found.", severity="error")
            return
        series_dict = cast("dict[str, Any]", series_data)

        # Count forward / earlier occurrences for the context line.
        forward = 0
        earlier = 0
        for occ in self.ctx.store.get_tasks_in_series(series_id):
            occ_date = actions.occurrence_date(occ.get("due"))
            if occ_date is None:
                continue
            if occ_date >= anchor:
                forward += 1
            else:
                earlier += 1

        def _apply(result: EditSeriesResult | None) -> None:
            if result is None:
                return
            # The dialog already validated the pattern, so this cannot fail.
            if result.pattern_str is not None:
                pattern = parse_recurrence(result.pattern_str)
            else:
                # Keep the stored calendar shape; apply time/duration (which
                # may clear) over it.
                from doxtr_doto.cli.recurrence import RecurrencePattern

                pattern = RecurrencePattern.from_dict(series_dict["pattern"])
                pattern.start_time = result.start_time
                pattern.duration_minutes = result.duration_minutes
            update = actions.update_series(
                self.ctx,
                series_id,
                pattern=pattern,
                title_template=result.title,
                anchor_date=anchor,
            )
            self.ctx.store.load()
            self.refresh_tasks()
            self.refresh_details()
            self.notify(
                f"Updated series {series_id} from {anchor.isoformat()} "
                f"({len(update.updated_task_ids)} occurrences)."
            )

        self.push_screen(
            self.edit_series_screen_class(
                series_id,
                series_dict,
                anchor,
                forward,
                earlier,
                width_percent=actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def action_series_next(self) -> None:
        """Jump the selection to the next occurrence of the current series (``e n``).

        The forward half of the series-navigation pair (shown in the ``e`` Edit
        domain only for a series occurrence, alongside ``e E`` / ``e D``).
        Delegates to :meth:`_move_in_series`; a no-op at the last occurrence
        (clamp, with a subtle notify) rather than wrapping, so the user keeps
        their sense of chronological position within the series.
        """
        self._move_in_series(1)

    def action_series_prev(self) -> None:
        """Jump the selection to the previous occurrence of the series (``e p``).

        The backward counterpart of :meth:`action_series_next`; a no-op at the
        first occurrence (see that method).
        """
        self._move_in_series(-1)

    def _move_in_series(self, delta: int) -> None:
        """Move the selection to a neighbouring occurrence of its own series.

        Shared by :meth:`action_series_next` (``delta == 1``) and
        :meth:`action_series_prev` (``delta == -1``). The jump follows
        OCCURRENCE order (the series' tasks sorted by due date), independent of
        the current list sort / filter, so it always steps to the adjacent
        meeting in the series regardless of how the board is arranged.

        Resolution mirrors the series-aware actions (:meth:`action_edit_series`
        etc.): the selected task is resolved to its owning store via
        :func:`doxtr_doto.cli.id_resolver.resolve_task_ref` (so a foreign-repo
        series in GLOBAL scope resolves against the right store), the store's
        :meth:`~doxtr_doto.sync.json_store.JsonTaskStore.get_tasks_in_series`
        yields the occurrences in due-date order, and the neighbour's bare
        local id is mapped back to the display id the active view selects on
        (:meth:`_display_id_for_repo`).

        Edge behaviour: at the first (``delta < 0``) or last (``delta > 0``)
        occurrence the move clamps (no wrap) and emits a subtle notify, keeping
        the user's position. A non-series selection, an unresolvable ref, or a
        neighbour that is currently filtered out of the view are all graceful
        no-ops (the last notifies, since the target exists but is hidden).

        Args:
            delta: ``1`` to step to the next occurrence, ``-1`` to the previous.
        """
        from doxtr_doto.cli.id_resolver import resolve_task_ref

        selected = self._current_selected_id()
        if not selected:
            return
        ref = self._action_ref(selected)
        resolved = resolve_task_ref(self.ctx, ref)
        if resolved is None:
            return
        task = resolved.store.get_task(resolved.task_id)
        if task is None:
            return
        series_id = task.get("series_id")
        if not isinstance(series_id, str) or not series_id:
            return
        occurrences = resolved.store.get_tasks_in_series(series_id)
        local_ids = [str(occ.get("id")) for occ in occurrences]
        try:
            index = local_ids.index(str(resolved.task_id))
        except ValueError:
            return
        target = index + delta
        if target < 0 or target >= len(local_ids):
            edge = "first" if delta < 0 else "last"
            self.notify(f"Already at the {edge} occurrence in this series.")
            return
        display_id = self._display_id_for_repo(resolved.repo, local_ids[target])
        if not self.select_task(display_id):
            word = "Previous" if delta < 0 else "Next"
            self.notify(f"{word} occurrence is not currently visible (filtered out).")
            return
        self.refresh_details()
        self.refresh_task_time()

    def _display_id_for_repo(self, repo: str, local_id: str) -> str:
        """Map an owning ``repo`` + bare ``local_id`` to the view's display id.

        The repo-aware generalisation of :meth:`_display_id_for` (which only
        resolves the *current* repo): series navigation may step to an
        occurrence owned by a foreign repo in GLOBAL scope, so the lookup keys
        on the preserved ``_repo`` / ``_local_id`` tags of the gathered
        :attr:`_tasks` for the given ``repo``. Falls back to ``local_id``
        unchanged when no visible row matches (the occurrence is filtered out,
        so :meth:`select_task` will no-op and the caller notifies).

        Args:
            repo: The occurrence's owning repo name.
            local_id: The occurrence's bare local id.

        Returns:
            The display id the active view selects on, or ``local_id`` when it
            cannot be mapped.
        """
        for task in self._tasks:
            if task.get("_repo") == repo and str(task.get("_local_id")) == local_id:
                return str(task.get("id", local_id))
        return local_id

    def action_delete_task(self) -> None:
        """Delete the selected entry after a yes/no confirmation (``e d``).

        Pushes a plain :attr:`confirm_screen_class`; on confirm the task is
        deleted via :func:`doxtr_doto.cli.tui.actions.delete_task` (which prunes
        the owning series link in the store) and the board/details refreshed.
        """
        selected = self._current_selected_id()
        if not selected:
            return
        ref = self._action_ref(selected)

        def _apply(result: ConfirmResult | None) -> None:
            if result is not ConfirmResult.CONFIRM:
                return
            if actions.delete_task(self.ctx, ref):
                self.ctx.store.load()
                self.notify(f"Deleted {selected}.")
                self.refresh_tasks()
                self.refresh_details()
            else:
                self.notify(f"Could not delete {selected}.", severity="error")

        self.push_screen(
            self.confirm_screen_class(
                f"Delete {selected}? This cannot be undone.",
                confirm_label="Delete",
                width_percent=actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def action_delete_series(self) -> None:
        """Delete the selected occurrence's whole series (``e D``).

        Shown only for a series occurrence. Pushes a three-way
        :attr:`confirm_screen_class` offering "Delete series + tasks", "Keep
        tasks, remove series" (parity with the CLI ``--keep-tasks``) and
        Cancel. The chosen branch calls
        :func:`doxtr_doto.cli.tui.actions.delete_series` with the matching
        ``delete_tasks`` flag, then refreshes and notifies (mirroring the CLI
        messages).
        """
        selected = self._current_selected_id()
        if not selected:
            return
        task = actions.find_task(self.ctx, self._action_ref(selected))
        if task is None:
            return
        series_id = task.get("series_id")
        if not isinstance(series_id, str) or not series_id:
            self.notify("Selected task is not part of a series.")
            return
        series_data = self.ctx.store.get_series(series_id)
        if series_data is None:
            self.notify(f"Series {series_id} not found.", severity="error")
            return
        task_count = len(series_data.get("task_ids", []))

        def _apply(result: ConfirmResult | None) -> None:
            if result is None or result is ConfirmResult.CANCEL:
                return
            delete_tasks = result is ConfirmResult.CONFIRM
            success, deleted = actions.delete_series(self.ctx, series_id, delete_tasks=delete_tasks)
            if not success:
                self.notify(f"Could not delete series {series_id}.", severity="error")
                return
            self.ctx.store.load()
            self.refresh_tasks()
            self.refresh_details()
            if delete_tasks:
                self.notify(f"Deleted series {series_id} ({len(deleted)} tasks).")
            else:
                self.notify(f"Deleted series {series_id} (kept {task_count} tasks).")

        self.push_screen(
            self.confirm_screen_class(
                f"Delete series {series_id} and its {task_count} tasks?",
                confirm_label="Delete series + tasks",
                keep_tasks_label="Keep tasks, remove series",
                width_percent=actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def action_assign_due(self) -> None:
        """Assign the selected calendar day to the highlighted no-due task (``A``).

        Feature C, scoped to the calendar layout (a harmless no-op in every
        other layout). When the calendar's "No due date" region holds a
        highlighted task and a calendar day is selected, this assigns the
        selected day as that task's ``due`` by writing it through
        :func:`doxtr_doto.cli.tui.actions.update_task` (the single ``doto
        update`` path, so the mutation never duplicates business logic). The
        task then leaves the no-due bucket and appears under that day's "Due"
        list; the task set / board / details are refreshed and the user is
        notified. It is a documented no-op (with a notify) when no no-due task
        is highlighted - e.g. focus is on the grid or Due region, or the
        no-due list is empty.
        """
        if self.layout_view is not TuiLayout.CALENDAR:
            return
        calendar = self.query_one(self.calendar_view_class)
        task_id = calendar.assign_task_id()
        if task_id is None:
            self.notify("No undated task highlighted to assign a due date.")
            return
        due = calendar.selected
        if actions.update_task(self.ctx, self._action_ref(task_id), {"due": due}):
            self.notify(f"{task_id} due {due}.")
            # refresh_tasks() refreshes the table + rebuilds the alt-views +
            # refreshes details; adding refresh_task_time() covers the
            # selection-driven task-time pane, giving one refresh path (the
            # old _refresh_calendar_focus() call duplicated the rebuild).
            self.refresh_tasks()
            self.refresh_task_time()
        else:
            self.notify(f"Could not assign due date to {task_id}.", severity="error")

    def _open_edit(self, selected: str) -> None:
        """Open the edit dialog for ``selected`` and apply the result.

        The single place the :attr:`edit_task_screen_class` modal is pushed, so
        both the ``e`` keybinding (:meth:`action_edit`) and the card viewer's
        ``e`` (:meth:`_open_card_viewer`, Feature 4) reuse the same edit flow:
        the submitted updates are written via
        :func:`doxtr_doto.cli.tui.actions.update_task` and the board/details
        are refreshed, never duplicating the edit business logic.

        Args:
            selected: The task id to edit.
        """
        task = actions.find_task(self.ctx, self._action_ref(selected))
        if task is None:
            return
        edit_task = {"id": selected, **task}

        def _apply(updates: dict[str, Any] | None) -> None:
            if not updates:
                return
            from doxtr_doto.exceptions import DotoValidationError

            try:
                applied = actions.update_task(self.ctx, self._action_ref(selected), updates)
            except DotoValidationError as exc:
                self.notify(str(exc), severity="error")
                return
            if applied:
                self.notify(f"Updated {selected}.")
                self.refresh_tasks()
                self.refresh_details()

        self.push_screen(
            self.edit_task_screen_class(
                edit_task,
                list(self.ctx.config.statuses),
                list(self.ctx.config.priorities),
                known_assignee_names(self.ctx),
                known_tag_names(self.ctx),
                actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def action_edit_body(self) -> None:
        """Open the focused body/note editor for the current task (``n``)."""
        selected = self._current_selected_id()
        if not selected:
            return
        self._open_edit_body(selected)

    def _open_edit_body(self, selected: str) -> None:
        """Open the body-only editor for ``selected`` and apply the result.

        The single place :attr:`edit_body_screen_class` is pushed, so both the
        ``n`` keybinding (:meth:`action_edit_body`) and the card viewer's ``n``
        (:meth:`CardViewerScreen.action_edit_body`, routed through
        :meth:`_open_card_viewer`) reuse the same flow. The edited body is
        written via :func:`doxtr_doto.cli.tui.actions.update_task` - the single
        ``doto update`` path - and the board/details refreshed. The modal
        dismisses with the new body string (``""`` clears the body) or ``None``
        to leave it untouched; an unchanged value is a harmless no-op write.

        Args:
            selected: The task id whose body to edit.
        """
        task = actions.find_task(self.ctx, self._action_ref(selected))
        if task is None:
            return
        edit_task = {"id": selected, **task}

        def _apply(body: str | None) -> None:
            if body is None:
                return
            if body == (task.get("body") or ""):
                return
            if actions.update_task(self.ctx, self._action_ref(selected), {"body": body}):
                self.notify(f"Updated note for {selected}.")
                self.refresh_tasks()
                self.refresh_details()

        self.push_screen(
            self.edit_body_screen_class(
                edit_task,
                actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def action_toggle_timer(self) -> None:
        """Start or stop the focus timer on the selected task."""
        selected = self._current_selected_id()
        if not selected:
            return
        result = actions.toggle_timer(self.ctx, self._action_ref(selected))
        if result == "started":
            self.notify(f"Started focus timer for {selected}.")
        elif result == "stopped":
            self.notify(f"Stopped focus timer for {selected}.")
        else:
            self.notify(f"Could not resolve {selected}.", severity="error")
            return
        self.refresh_tasks()
        self.refresh_counters()

    def action_start_work(self) -> None:
        """Start/stop working on the target task(s) (the flat ``w`` key).

        Routes through :meth:`_bulk_apply` (so a multi-selection is honored)
        calling :func:`doxtr_doto.cli.tui.actions.start_work`, which sets the
        doto in-progress and starts the focus timer on the START branch and
        stops the timer (status unchanged) on a second press. The counters are
        refreshed afterwards so the live Work/Focus readouts update at once.
        """
        ctx = self.ctx
        self._bulk_apply(
            lambda task_id: actions.start_work(ctx, self._action_ref(task_id)),
            lambda task_id, result: (
                f"Started working on {task_id}."
                if result == "started"
                else f"Stopped working on {task_id}."
            ),
            lambda count: f"Toggled working on {count} tasks.",
        )
        self.refresh_counters()

    def action_clock_out(self) -> None:
        """Stop the focus timer and the global work clock."""
        stopped = actions.clock_out(self.ctx)
        if stopped:
            self.notify("Clocked out. Work clock stopped.")
        else:
            self.notify("Work clock was not running.")
        self.refresh_tasks()
        self.refresh_counters()

    def action_configure_breaks(self) -> None:
        """Open the breaks + work-week configurator and persist the result."""
        state = self.ctx.global_store.load()

        def _apply(result: tuple[list[Any], list[int]] | None) -> None:
            if result is None:
                return
            breaks, workweek_days = result
            new_state = self.ctx.global_store.load()
            new_state.breaks = breaks
            new_state.workweek_days = workweek_days
            self.ctx.global_store.save(new_state)
            self.notify(
                f"Saved {len(breaks)} break(s); work week {weekday_range_label(workweek_days)}."
            )
            self.refresh_counters()
            # The work-week day set feeds the time-layout summary panel, so
            # rebuild it when that layout is active to reflect the new set.
            if self.layout_view is TuiLayout.TIME:
                self._rebuild_time_layout()

        self.push_screen(
            self.breaks_config_screen_class(list(state.breaks), list(state.workweek_days)),
            _apply,
        )

    def action_configure_detail_ratio(self) -> None:
        """Open the detail-pane ratio configurator and apply + persist it.

        Opened from the ``Config`` domain with ``c`` -> ``d``. Pushes
        :attr:`detail_ratio_screen_class` pre-populated with the current
        :attr:`detail_ratio`. On *Apply* the chosen ``"n/d"`` ratio is stored
        on the app, applied immediately to the live table-layout pane heights
        via :meth:`apply_detail_ratio` (so the change is visible without a
        restart), and persisted via
        :func:`doxtr_doto.cli.tui.actions.save_detail_ratio` so it is restored
        on the next ``doto tui`` launch. ``Escape`` leaves the ratio
        unchanged.
        """

        def _apply(ratio: str | None) -> None:
            if ratio is None:
                return
            self.detail_ratio = ratio
            actions.save_detail_ratio(self.ctx, ratio)
            self.apply_detail_ratio()
            self.notify(f"Detail pane set to {ratio} of the total height.")

        self.push_screen(self.detail_ratio_screen_class(self.detail_ratio), _apply)

    def action_configure_modal_width(self) -> None:
        """Open the task pop-up width configurator (``c`` -> ``m``).

        Pushes :attr:`modal_width_screen_class` pre-populated with the current
        :attr:`modal_width_ratio`. On *Apply* the chosen ``"n/d"`` ratio is
        stored on the app (so the next task pop-up - card viewer, edit or note
        - opens at the new width without a restart) and persisted via
        :func:`doxtr_doto.cli.tui.actions.save_modal_width_ratio` so it is
        restored on the next ``doto tui`` launch. ``Escape`` leaves the ratio
        unchanged.
        """

        def _apply(ratio: str | None) -> None:
            if ratio is None:
                return
            self.modal_width_ratio = ratio
            actions.save_modal_width_ratio(self.ctx, ratio)
            self.notify(f"Task pop-ups set to {ratio} of the terminal width.")

        self.push_screen(self.modal_width_screen_class(self.modal_width_ratio), _apply)

    # -- Calendar sync (``C`` domain) --------------------------------------
    #
    # Each action kicks off a Textual *thread* worker because provider
    # connect / list / push / OAuth are blocking network calls that would
    # freeze the UI if run on the event loop. The worker runs the Textual-free
    # orchestration in :mod:`doxtr_doto.cli.tui.calsync_tui` and marshals the
    # resulting notification back onto the UI thread. A notification is posted
    # up front so a slow network round-trip does not look like a dead key.
    def action_calsync_sync(self) -> None:
        """``C`` -> ``s``: sync every *displayed* calendar-enabled repo.

        Rather than syncing only the launch directory, this syncs each repo the
        TUI is currently showing (per the active scope and repo filter) that is
        itself configured for calendar sync, each with its own direction /
        conflict policy / calendar. pull/two-way directions import tasks, so the
        view is refreshed on success.
        """
        # Capture the view state on the UI thread; the worker runs off-thread.
        scope = self.scope
        repo_filter = tuple(self.view_prefs.repo_filter)
        self.notify("Syncing calendar...", title="Calendar sync")
        self._calsync_sync_worker(scope, repo_filter)

    def action_calsync_push(self) -> None:
        """``C`` -> ``p``: one-way push (doto -> calendar)."""
        self._run_calsync("push", "Pushing to calendar...")

    def action_calsync_pull(self) -> None:
        """``C`` -> ``l``: one-way pull (calendar -> doto), then refresh the view."""
        self._run_calsync("pull", "Pulling from calendar...", refresh_after=True)

    def action_calsync_status(self) -> None:
        """``C`` -> ``t``: show the current config + dry-run plan.

        ``status`` is computed from the local store/state (no network), so it
        runs inline rather than in a worker.
        """
        outcome = calsync_tui.status(self.ctx)
        self.notify(
            outcome.message,
            title=outcome.title,
            severity="information" if outcome.ok else "error",
        )

    def action_calsync_login(self) -> None:
        """``C`` -> ``i``: run the provider's interactive login."""
        self._run_calsync("login", "Opening login...")

    def action_calsync_logout(self) -> None:
        """``C`` -> ``o``: clear the cached provider token."""
        self._run_calsync("logout", "Clearing calendar token...")

    def action_calsync_resolve(self) -> None:
        """``C`` -> ``r``: resolve the selected task's sync conflict.

        Opens the keep-local/remote/both dialog for the currently selected
        task when it carries an unresolved ``_sync.conflict`` stash, then
        applies the choice through the shared
        :func:`doxtr_doto.calsync.resolve.resolve_conflict` helper (the same
        path as ``doto calsync resolve``) and clears the flag. A no-op (with a
        hint) when the selection has no recorded conflict.
        """
        from doxtr_doto.calsync.resolve import (
            ResolutionChoice,
            conflict_fields,
            resolve_conflict,
        )

        selected = self._current_selected_id()
        if not selected:
            return
        task = actions.find_task(self.ctx, self._action_ref(selected))
        if task is None:
            return
        task_dict = {"id": selected, **task}
        records = conflict_fields(task_dict)
        if not records:
            self.notify(
                f"{selected} has no unresolved sync conflict.",
                title="Calendar sync",
                severity="information",
            )
            return

        def _apply(choice: str | None) -> None:
            if choice is None:
                return
            try:
                updates = resolve_conflict(task_dict, ResolutionChoice(choice))
            except ValueError as exc:  # pragma: no cover - defensive
                self.notify(str(exc), title="Calendar sync", severity="error")
                return
            if actions.update_task(self.ctx, self._action_ref(selected), updates):
                self.notify(f"Resolved {selected} -> kept {choice}.", title="Calendar sync")
                self.refresh_tasks()
                self.refresh_details()

        self.push_screen(
            self.conflict_resolve_screen_class(
                selected,
                records,
                width_percent=actions.modal_width_percent(self.modal_width_ratio),
            ),
            _apply,
        )

    def _run_calsync(self, op: str, pending: str, *, refresh_after: bool = False) -> None:
        """Post a pending toast and dispatch the calsync ``op`` to a worker.

        Args:
            op: The :mod:`calsync_tui` function name to invoke
                (``sync``/``push``/``pull``/``login``/``logout``).
            pending: A short "working..." notification shown immediately so a
                slow network call still gives feedback.
            refresh_after: When True (pull), reload the task list on success so
                freshly imported/updated tasks appear without a manual rescan.
        """
        self.notify(pending, title="Calendar sync")
        self._calsync_worker(op, refresh_after)

    @work(thread=True, exclusive=True, group="calsync")
    def _calsync_worker(self, op: str, refresh_after: bool) -> None:
        """Thread worker: run the blocking calsync op, then notify on the UI thread.

        Exclusive within the ``calsync`` group so a second trigger while a sync
        is in flight supersedes the first rather than running two concurrent
        provider sessions against the same calendar/state.
        """
        fn = getattr(calsync_tui, op)
        try:
            outcome = fn(self.ctx)
        except Exception as exc:  # defensive: surface, don't crash the worker
            self.call_from_thread(self.notify, str(exc), title="Calendar sync", severity="error")
            return
        self.call_from_thread(
            self.notify,
            outcome.message,
            title=outcome.title,
            severity="information" if outcome.ok else "error",
        )
        if refresh_after and outcome.ok:
            self.call_from_thread(self._reload_after_calsync)

    @work(thread=True, exclusive=True, group="calsync")
    def _calsync_sync_worker(self, scope: Any, repo_filter: tuple[str, ...]) -> None:
        """Thread worker for ``C s``: sync every displayed calendar-enabled repo.

        Shares the ``calsync`` exclusive group with :meth:`_calsync_worker` so a
        sync never runs concurrently with another calendar operation. Scope and
        repo filter are captured on the UI thread and passed in. Refreshes the
        task view on success (pull/two-way may have imported tasks).
        """
        try:
            outcome = calsync_tui.sync_displayed(self.ctx, scope=scope, repo_filter=repo_filter)
        except Exception as exc:  # defensive: surface, don't crash the worker
            self.call_from_thread(self.notify, str(exc), title="Calendar sync", severity="error")
            return
        self.call_from_thread(
            self.notify,
            outcome.message,
            title=outcome.title,
            severity="information" if outcome.ok else "error",
        )
        if outcome.ok:
            self.call_from_thread(self._reload_after_calsync)

    def _reload_after_calsync(self) -> None:
        """Reload the task view after a pull imported/updated tasks.

        The worker mutates and saves ``ctx.store`` in place, so the task set
        the view gathers is already current; rebuilding the active layout picks
        up the imported/updated rows without a manual rescan.
        """
        self.refresh_tasks()

    def action_manage_work_time(self) -> None:
        """Open the work-time interval manager for today."""

        def _done(_result: None) -> None:
            self.refresh_counters()
            # The manager can add/edit/delete work-clock intervals, so the
            # ``time`` layout's day list and week/month/year summary panel may
            # now be stale. Rebuild them when that layout is active so the
            # summary reflects the changed intervals as soon as the modal
            # closes.
            if self.layout_view is TuiLayout.TIME:
                self._rebuild_time_layout()

        self.push_screen(self.work_time_screen_class(self.ctx), _done)

    def _stats_anchor(self) -> date | None:
        """Return the anchor date for a stats pop-up.

        When the ``time`` layout is active the anchor is the time view's
        currently selected day (so prev/next period navigation starts there);
        in every other layout the time view's selection is not meaningful, so
        the anchor is left as ``None`` and the pop-up defaults to local today.
        """
        if self.layout_view is not TuiLayout.TIME:
            return None
        from datetime import date as _date

        selected = self.query_one(self.time_view_class).selected_id()
        if selected is None:
            return None
        try:
            return _date.fromisoformat(selected)
        except ValueError:
            return None

    def action_work_stats(self) -> None:
        """Open the work-statistics pop-up (Feature: work statistics).

        Available from every layout (the ``S w`` stream is advertised globally
        in the hint bar). The pop-up anchors on the time view's selected day
        when the ``time`` layout is active, otherwise on local today, so
        prev/next period navigation starts from a sensible point.
        """
        self.push_screen(self.work_stats_screen_class(self.ctx, self._stats_anchor()))

    def action_task_time_stats(self) -> None:
        """Open the per-doto time-reporting pop-up (per-doto time stats).

        Available from every layout (the ``S t`` stream is advertised globally
        in the hint bar), mirroring :meth:`action_work_stats`. The pop-up
        anchors on the time view's selected day when the ``time`` layout is
        active, otherwise on local today, so prev/next period navigation starts
        from a sensible point.
        """
        self.push_screen(self.task_time_stats_screen_class(self.ctx, self._stats_anchor()))

    def action_edit_sessions(self) -> None:
        """Open the per-doto session editor for the highlighted doto (``t e``).

        Reachable from the task-centric layouts (table / list / kanban /
        calendar), where :meth:`_current_selected_id` resolves to a task id;
        it is a harmless no-op in the ``time`` layout (whose selection is a
        day, not a doto) and when nothing is selectable. The selected id (a
        bare ``id`` or namespaced ``repo#id``) is passed to
        :attr:`task_sessions_screen_class`, which resolves the owning repo
        store and edits that single doto's recorded sessions; on close the
        task set and live counters are refreshed so the new per-task totals
        show immediately.
        """
        if self.layout_view is TuiLayout.TIME:
            return
        selected = self._current_selected_id()
        if not selected:
            return

        def _done(_result: None) -> None:
            self.refresh_tasks()
            self.refresh_task_time()
            self.refresh_counters()

        self.push_screen(self.task_sessions_screen_class(self.ctx, selected), _done)

    def action_add(self) -> None:
        """Open the add-task modal and create the task on submit.

        The modal is field-configurable (see :class:`AddTaskScreen`): this
        forwards the active config (so ``tui_add_fields`` / ``tui_add_defaults``
        select which fields show and their prefills), the configured statuses /
        priorities (for the select fields) and the cross-repo known assignee /
        tag names (for auto-complete). The user can also choose the target
        repository (defaulting to the current repo). On submit every collected
        field on the :class:`AddTaskResult` is forwarded to
        :func:`doxtr_doto.cli.tui.actions.add_task`, and the notification names
        the repo when it differs from the current one.
        """
        current = data.current_repo(self.ctx)

        def _created(result: AddTaskResult | None) -> None:
            if result is None:
                return
            from doxtr_doto.exceptions import DotoValidationError

            try:
                task_id = actions.add_task(
                    self.ctx,
                    result.title,
                    priority=result.priority,
                    status=result.status,
                    assignee=result.assignee,
                    tags=result.tags,
                    due=result.due,
                    estimate=result.estimate,
                    depends_on=result.depends_on,
                    body=result.body,
                    progress=result.progress,
                    raci=result.raci,
                    repo=result.repo,
                )
            except DotoValidationError as exc:
                self.notify(str(exc), severity="error")
                return
            if result.repo.path == current.path:
                # ``add_task`` writes through a store instance resolved for the
                # target repo; for the *current* repo that is a distinct
                # instance from ``ctx.store``, whose in-memory cache would
                # otherwise stay stale and hide the new task in LOCAL scope
                # (GLOBAL re-reads each repo from disk). Reload so the task is
                # present for the refresh - and selectable below. Mirrors the
                # reload discipline in :func:`actions.toggle_timer` (reused by
                # :func:`actions.start_work`), which reloads the resolved
                # store before acting to keep its decision off a stale cache.
                self.ctx.store.load()
                self.notify(f"Added {task_id}.")
            else:
                self.notify(f"Added {task_id} in {result.repo.name}.")
            self.refresh_tasks()
            # Auto-select the freshly created task so its row is highlighted
            # and scrolled into view (config-gated, default on). Selecting via
            # the overridable :meth:`select_task` seam reuses each view's
            # existing cursor-move / smart-scroll path; the alt-view render is
            # rebuilt a second time afterwards (``refresh_tasks`` already
            # rebuilt it once) because ``select_task`` mutates each alt-view's
            # cursor state *after* that refresh-driven rebuild, so the views
            # need a fresh rebuild to paint the new highlight (the TABLE path
            # repaints itself through the DataTable RowHighlighted message).
            if self.ctx.config.tui_auto_select_new_task and self.select_task(task_id):
                if self._active_view() is not None:
                    self._rebuild_alt_views()
                    self.refresh_details()
                    self.refresh_task_time()

        self.push_screen(
            self.add_task_screen_class(
                data.list_repos(self.ctx),
                current,
                config=self.ctx.config,
                statuses=list(self.ctx.config.statuses),
                priorities=list(self.ctx.config.priorities),
                known_assignees=known_assignee_names(self.ctx),
                known_tags=known_tag_names(self.ctx),
            ),
            _created,
        )

    def action_add_series(self) -> None:
        """Open the add-series dialog and create the series on submit.

        Mirrors :meth:`action_add` for recurring series: the dialog collects a
        recurrence pattern (with dedicated ``at`` / ``for`` start-time /
        duration fields), from/until dates and the target repository. On
        submit the validated :class:`AddSeriesResult` is turned into a parsed
        pattern + task defaults and handed to
        :func:`doxtr_doto.cli.tui.actions.add_series` -- the SAME reusable
        builder the CLI ``doto add --repeat`` path uses -- so the TUI never
        duplicates the occurrence/series-building code. The occurrence limit is
        enforced here (as in the CLI) before building, and the notification
        names the repo when it differs from the current one.
        """
        from doxtr_doto.cli.commands.add import MAX_OCCURRENCES
        from doxtr_doto.cli.recurrence import generate_occurrences, parse_recurrence

        current = data.current_repo(self.ctx)

        def _created(result: AddSeriesResult | None) -> None:
            if result is None:
                return
            # Parse once more here (the dialog already validated it, so this
            # cannot fail) to get the structured pattern for the builder.
            pattern = parse_recurrence(result.pattern_str)

            # Enforce the occurrence limit before building, mirroring the CLI.
            config = self.ctx.config
            max_occurrences = getattr(config, "max_occurrences", MAX_OCCURRENCES)
            occurrences = list(generate_occurrences(pattern, result.from_date, result.until_date))
            if not occurrences:
                self.notify(
                    "No occurrences for the given pattern and date range.",
                    title="No series created",
                    severity="warning",
                )
                return
            if len(occurrences) > max_occurrences:
                self.notify(
                    f"Would create {len(occurrences)} tasks (limit: {max_occurrences}).",
                    title="Series too large",
                    severity="error",
                )
                return

            task_defaults: dict[str, Any] = {
                "assignee": config.default_assignee or None,
                "priority": config.default_priority,
                "status": config.default_status,
                "tags": [],
                "depends_on": [],
                "body": None,
            }
            series = actions.add_series(
                self.ctx,
                title_template=result.title,
                pattern=pattern,
                start_date=result.from_date,
                end_date=result.until_date,
                task_defaults=task_defaults,
                repo=result.repo,
            )
            if result.repo.path == current.path:
                # Reload the current repo's store so the freshly created tasks
                # are present for the refresh (mirrors ``action_add``).
                self.ctx.store.load()
                self.notify(f"Created series {series.series_id} ({series.occurrence_count} tasks).")
            else:
                self.notify(
                    f"Created series {series.series_id} "
                    f"({series.occurrence_count} tasks) in {result.repo.name}."
                )
            self.refresh_tasks()

        self.push_screen(
            self.add_series_screen_class(
                data.list_repos(self.ctx),
                current,
                width_percent=actions.modal_width_percent(self.modal_width_ratio),
            ),
            _created,
        )

    def action_filter(self) -> None:
        """Open the filter modal and apply the entered search term."""

        def _apply(term: str | None) -> None:
            if term is None:
                return
            self.filter_term = term
            self.refresh_tasks()

        self.push_screen(FilterScreen(), _apply)

    def action_view_prefs(self) -> None:
        """Open the filter/sort pop-up and apply + persist the result (Feature C).

        Pushes :attr:`view_prefs_screen_class` pre-populated with the current
        :attr:`view_prefs` and the known tags/priorities/repositories. On
        submit the new preferences are stored on the app, persisted via
        :func:`doxtr_doto.cli.tui.actions.save_view_prefs` (the sort-memory
        requirement, so the last filter/sort state is remembered on the next
        launch), and the task list and repo tree are refreshed (so the tree's
        repo-selection markers stay in sync with the pop-up). ``Escape``
        leaves the current prefs unchanged.
        """

        def _apply(prefs: ViewPrefs | None) -> None:
            if prefs is None:
                return
            self.view_prefs = prefs
            actions.save_view_prefs(self.ctx, prefs)
            self.refresh_tasks()
            self.refresh_repos()

        self.push_screen(
            self.view_prefs_screen_class(
                self.view_prefs,
                known_tag_names(self.ctx),
                list(self.ctx.config.priorities),
                [repo.name for repo in data.list_repos(self.ctx)],
                int(getattr(self.ctx.config, "tui_recent_done_days", 10)),
            ),
            _apply,
        )

    def action_rescan(self) -> None:
        """Rediscover repositories and refresh the repo tree."""
        count = actions.rescan_repos(self.ctx)
        self.notify(f"Rescanned repos ({count} found).")
        self.refresh_repos()
        self.refresh_tasks()

    def action_toggle_scope(self) -> None:
        """Toggle between Local and Global display scope."""
        self.scope = DisplayScope.GLOBAL if self.scope is DisplayScope.LOCAL else DisplayScope.LOCAL
        self.refresh_repos()
        self.refresh_tasks()

    def action_help(self) -> None:
        """Show the top-level keybinding help router modal."""
        self.push_screen(self.help_screen_class(self.keymap))


#: The stream-keymap registry: the single source of truth driving the
#: dispatcher (:meth:`DotoApp.on_key` / :meth:`DotoApp._run_entry`), the hint
#: bar (:class:`doxtr_doto.cli.tui.widgets.KeyHintBar`) and the help screens
#: (:class:`HelpScreen` / :class:`DomainHelpScreen`), so the three consumers
#: cannot drift. Each prefix maps to a :class:`DomainSpec` whose ``entries_fn``
#: builds that domain's sub-keys per-app (status rows are dynamic - see
#: :meth:`DotoApp._status_key_entries`). Each domain implicitly owns ``?``
#: (its help) and ``escape`` (cancel), rendered by the bar and handled by the
#: dispatcher rather than stored per row. Mirrors the ``ALT_LAYOUTS``
#: discipline.
KEYMAP: dict[str, DomainSpec] = {
    "e": DomainSpec(
        "Edit",
        "task",
        lambda app: [
            KeyEntry("e", "edit", "Edit entry"),
            KeyEntry("d", "delete_task", "Delete entry"),
            KeyEntry("P", "set_parent", "Set parent…"),
            *(
                [
                    KeyEntry("E", "edit_series", "Edit series (from here forward)"),
                    KeyEntry("D", "delete_series", "Delete series"),
                    KeyEntry("n", "series_next", "Next in series"),
                    KeyEntry("p", "series_prev", "Prev in series"),
                ]
                if app._selected_is_series_member()
                else []
            ),
        ],
    ),
    "s": DomainSpec(
        "State",
        "task",
        lambda app: [
            *app._status_key_entries(),
            KeyEntry("n", "cycle_status", "Next"),
            KeyEntry("p", "cycle_status_prev", "Prev"),
        ],
    ),
    "t": DomainSpec(
        "Time",
        "task_or_global",
        lambda app: [
            KeyEntry("t", "toggle_timer", "Toggle timer"),
            KeyEntry("o", "clock_out", "Clock out"),
            KeyEntry("w", "manage_work_time", "Work time"),
            KeyEntry("e", "edit_sessions", "Edit sessions"),
        ],
    ),
    "c": DomainSpec(
        "Config",
        "global",
        lambda app: [
            KeyEntry("b", "configure_breaks", "Breaks + week"),
            KeyEntry("d", "configure_detail_ratio", "Detail size"),
            KeyEntry("m", "configure_modal_width", "Pop-up width"),
        ],
    ),
    "S": DomainSpec(
        "Stats",
        "global",
        lambda app: [
            KeyEntry("w", "work_stats", "Work stats"),
            KeyEntry("t", "task_time_stats", "Per-doto time"),
        ],
    ),
    "C": DomainSpec(
        "Calendar Sync",
        "global",
        lambda app: [
            KeyEntry("s", "calsync_sync", "Sync (per direction)"),
            KeyEntry("p", "calsync_push", "Push -> calendar"),
            KeyEntry("l", "calsync_pull", "Pull <- calendar"),
            KeyEntry("t", "calsync_status", "Status / plan"),
            KeyEntry("r", "calsync_resolve", "Resolve conflict"),
            KeyEntry("i", "calsync_login", "Login"),
            KeyEntry("o", "calsync_logout", "Logout"),
        ],
    ),
}

# Bind the module-level registry as the default :attr:`DotoApp.keymap` now that
# KEYMAP exists (it is declared below the class, so the class body only
# annotates the attribute). A child theme overrides ``keymap`` on its subclass;
# the dispatcher / hint bar / help screens all read ``self.keymap``.
DotoApp.keymap = KEYMAP
