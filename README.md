# doxtr-doto - Documentation Task Management for Sphinx

**doxtr-doto** (documentation task open) is a Sphinx extension for managing documentation tasks with structured metadata, bidirectional sync with JSON storage, and a companion CLI tool.

## Features

- **Structured task directives** - Define tasks with priorities, assignees, due dates, tags, and dependencies
- **Task lists and summaries** - Display filtered, sorted task lists and statistics
- **Styled PDF task boxes** - Each task renders as a `tcolorbox` with a high-contrast title bar and readable body (no more white-on-white boxes), in a roomy `default` or dense `compact` layout (`doto_latex_layout`, overridable per directive with `:latex-layout:`)
- **Stacked Font Awesome metadata icons** - PDF task boxes stack a semantic FA icon above each metadata label (calendar for due, user for assignee, flag for priority, etc.), degrading gracefully when Font Awesome is unavailable
- **Task-list icon modes** - Render list cells as Font Awesome icons, icon+text, or text, with clickable task IDs/titles
- **Cross-references** - Link to tasks with the `:doto:` role; PDF cross-references are clickable hyperlinks that jump to the task box
- **Bidirectional sync** - Keep RST files and JSON storage in sync with 3-way merge
- **Auto-archiving** - Automatically archive completed tasks (on by default). Archived tasks are removed from their RST file, preserved in JSON, and shown on a dedicated archive page; reopening restores a task to the same place in its original file.
- **CLI tool** - Manage tasks from the command line
- **Interactive TUI** - Optional 3-pane terminal UI (`doto tui`) with configurable task-list layout views (table / list / kanban / calendar / time, cycled with `v` / `V` and persisted as your default). The kanban board draws framed, fixed-size **square cards** (long bodies clipped with an ellipsis), marks the selected card with a highlighted **frame**, and (like the list and calendar layouts) opens a **card viewer popup** on `Enter` (full task detail with a scrollable body) from which `e` opens the edit dialog; the table layout instead reveals details in its details pane. The calendar view's `Tab` cycles through the month grid, the day's `Due` task list, and the `No due date` list so you can edit / close those tasks in place, with `A` assigning the selected day as a highlighted undated task's due date. Also: live work/focus timers, a top-right elapsed-time display (the whole day's accumulated work time with the current session in parentheses, plus the highlighted task's total), editable due dates, a repo-aware **add-task modal** (choose which repository a new task is created in), a **filter & sort pop-up** (`F`: hide completed, due today/this week, by tag or priority; sort by due/priority/tag/`next`, remembered across sessions), the **active (time-recorded) task pinned to the top** of every view, Vim and arrow-key navigation, a **two-key "stream" keymap** that groups related actions under memorable prefixes (`e` edit/delete entry or series, `s` state, `t` time, `c` config, `S` stats) with a **context-sensitive hint bar** pinned to the bottom (pressing a prefix repaints the bar with that domain's sub-keys, so the scheme is self-documenting), a flat `w` to start/stop working (sets a doto in-progress and starts its focus timer in one press), and a once-per-day kickstart nudge
- **Theming** - Customizable HTML and LaTeX output
- **Charts** - Task summaries with built-in SVG charts, or richer [plotly](https://plotly.com/python/) charts (pie, bar, stacked-bar, progress, burndown)
- **Doxtr integration** - Optional integration with doxtr-pdf-theme-core: semantic-palette-derived task colors and automatic landscape rotation for wide task tables

## Installation

```bash
pip install doxtr-doto

# With CLI support
pip install doxtr-doto[cli]

# With plotly charts (pie/bar/stacked-bar/progress/burndown)
pip install doxtr-doto[charts]

# With the interactive terminal UI (textual)
pip install doxtr-doto[tui]

# With calendar sync (Google / Microsoft / Apple / CalDAV)
pip install doxtr-doto[calendar]

# Full installation
pip install doxtr-doto[all]
```

The `charts` extra installs `plotly>=5` and `kaleido`. Static image export
(used for HTML `<img>` charts and PDF `\includegraphics`) additionally requires
a Chrome/Chromium install for kaleido; when plotly, kaleido, or Chrome are
unavailable, `doto-summary` automatically falls back to built-in,
dependency-free charts so the build never breaks:

- **HTML** falls back to inline SVG charts.
- **PDF/LaTeX** falls back to native TikZ charts (`\dotochart*` macros in
  `doto.sty`), so the PDF always renders a real visual chart — no browser or
  kaleido required. A child theme can restyle these by redefining the
  `\dotochart*` macros / `dotochart` environment.

## Quick Start

1. Add `doxtr_doto` to your Sphinx extensions in `conf.py`:

```python
extensions = [
    "doxtr_doto",
]
```

2. Create a task in your documentation:

```rst
.. doto:: Implement user authentication
   :id: TASK-001
   :assignee: alice
   :priority: high
   :status: open
   :due: 2026-08-15
   :tags: security, backend

   Detailed description of the task goes here.
```

3. Display a task list:

```rst
.. doto-list::
   :status: open, in-progress
   :sort: priority
   :format: table
```

4. Reference tasks inline:

```rst
This relates to :doto:`TASK-001`.
```

## Directive Reference

### `.. doto::` - Task Definition

Creates a task with structured metadata.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `:id:` | string | Auto-generated | Unique task identifier (auto-generated IDs are written back into the RST file on the next build to keep them stable) |
| `:assignee:` | string | None | Person responsible |
| `:priority:` | enum | `medium` | `low`, `medium`, `high`, `critical` |
| `:status:` | enum | `open` | `open`, `in-progress`, `blocked`, `done` |
| `:due:` | date | None | Due date (`YYYY-MM-DD`), optionally with a time — see [Due dates with time](#due-dates-with-time) |
| `:estimate:` | duration | None | Expected duration (`5m`, `4h`, `1h30m`, or bare minutes); used by [calendar-sync](#calendar-sync) to size the event |
| `:tags:` | list | None | Comma-separated categories |
| `:depends-on:` | list | None | Comma-separated task IDs |
| `:raci:` | string | None | RACI roles as `role name` pairs (see [RACI Roles](#raci-roles)) |

The task title (the directive argument) may span multiple indented
continuation lines in your RST source. doto normalizes it to a single logical
line when stored (every run of whitespace, including the embedded newlines and
continuation indentation, is collapsed to one space), so the title renders as
one line everywhere it is read back - the `doto tui` list view, HTML/PDF
output, JSON export, and the CLI.

#### Due dates with time

The `:due:` option is normally a calendar date (`YYYY-MM-DD`). It can also
carry an optional **clock time** appended to the date, separated by a single
space or an ISO-style `T`:

```rst
.. doto:: Ship the release
   :id: REL-001
   :due: 2026-08-15 16:00      # HH:MM

.. doto:: Stand-up
   :id: SU-001
   :due: 2026-08-15 16h        # hour shorthand -> 16:00

.. doto:: Backup window closes
   :id: BK-001
   :due: 2026-08-15 16:00:31   # HH:MM:SS
```

Accepted time syntaxes (appended to the date): `HH:MM` (e.g. `16:00`), the
hour shorthand `HHh` (e.g. `16h` → `16:00`), and `HH:MM:SS` (e.g. `16:00:31`).
A due with **no** time behaves exactly as before — it stays a plain date and
renders, sorts, and serializes identically.

The time is **naive and local** (no timezone): it is interpreted in your local
wall-clock, matching how doto already models dates. This keeps the data model
simple and is the foundation a later calendar-sync feature builds on.

Storage is a single string that is either `YYYY-MM-DD` or
`YYYY-MM-DDTHH:MM[:SS]`, round-tripped losslessly through RST and JSON (seconds
are only kept when non-zero, so `16:00` stays `16:00`). It renders as
`YYYY-MM-DD HH:MM` in task boxes and lists.

**Overdue with a time:** a date-only due becomes overdue once the day has fully
passed (a task due *today* is not overdue). A time-bearing due becomes overdue
once that specific local instant has passed — so a task due today at 16:00
flips to overdue at 16:00 local, not at midnight.

### `.. doto-list::` - Task List

Displays a filtered list of tasks.

**Filter Options:** `:assignee:`, `:priority:`, `:status:`, `:tags:`, `:due-before:`, `:due-after:`, `:exclude-status:`

**Display Options:** `:sort:`, `:order:`, `:limit:`, `:format:` (table/list/cards/kanban/calendar/email), `:show-archived:`, `:columns:`, `:icon-mode:` (icon/icon-text/text), `:visible-tasks:` (email view scroll cap)

Selectable `:columns:` include `id`, `title`, `priority`, `status`, `assignee`,
`due`, `tags`, `created`, `updated`, `progress`, and `estimate`. `estimate` and
`progress` are also valid `:sort:` keys and sort numerically (shortest/lowest
first; tasks without a value sort last).

Task IDs and titles in every list format are clickable links to the task box.
The `:icon-mode:` option overrides the global `doto_list_icon_mode` config for
a single directive. The `:visible-tasks:` option (email view only) overrides the
global `doto_list_visible_tasks` config and caps how many list rows are visible
at once in the scrollable list pane. An explicit `0` means show all (no cap);
omitting the option (or leaving it empty) falls back to `doto_list_visible_tasks`;
any positive integer caps the visible rows.

#### Layout views (`:format:`)

The `:format:` option is the per-directive toggle for the task-list layout:

| Format | Layout | Interaction |
| --- | --- | --- |
| `table` | Columns defined by `:columns:` | Static |
| `list` | One task per line | Static |
| `cards` | One card per task | Static |
| `kanban` | Columns by status (from your configured `doto_statuses`, e.g. To Do / In Progress / Blocked / Done) | Drag cards between columns (client-side) |
| `calendar` | Month grid; tasks on their due date | Click a day to reveal its tasks (client-side) |
| `email` | Three panes: status tree (left), task list (top-right), detail (bottom-right) | Select a tree node / list row (client-side) |

The `kanban`, `calendar`, and `email` views are HTML-interactive layouts backed
by a vendored, dependency-free JavaScript asset (`doto-views.js`, registered
automatically for HTML builders only). Because a static Sphinx build has **no
backend**, these interactions are **client-side and visual only**:

- **kanban** — dragging a card to another column updates the card's column and
  status badge in the page, but the change is not persisted; a reload restores
  the server-rendered board.
- **calendar** — clicking a day expands that day's task panel in the page.
- **email** — selecting a status node filters the list, and selecting a list
  row populates the detail pane; both are in-page only. The top-right list pane
  is scrollable and caps how many rows are visible at once (default **5**),
  controlled by `:visible-tasks:` (per directive) or the global
  `doto_list_visible_tasks` config. The cap is a scroll viewport only — every
  matching task still renders and stays clickable; set it to `0` to show all
  rows with no cap. The resolved count is emitted on `.doto-email-list` as both
  a `data-doto-visible-tasks` attribute and a `--doto-visible-tasks` CSS custom
  property, and the shipped CSS computes the pane's `max-height` from it, so the
  cap works as pure CSS even when JavaScript is unavailable. A child theme that
  restyles `.doto-email-list-item` (padding/font) should also set
  `--doto-row-height` on `.doto-email-list` so the viewport stays aligned to N
  rows.

All three degrade gracefully: the markup is fully present and readable when
JavaScript is unavailable, and LaTeX/epub builds fall back to a static table
(calendar) or grouped list (kanban/email) rather than erroring. The views'
templates (`doto-list-kanban.html`, `doto-list-calendar.html`,
`doto-list-email.html`) and the CSS (namespaced `doto-kanban-*`,
`doto-calendar-*`, `doto-email-*`) are child-theme overridable like the other
list formats (drop replacements into `<srcdir>/_doto/templates/html/` or ship a
custom theme CSS). The interaction script is overridable too: a
`<srcdir>/_doto/html/doto-views.js` fully replaces the bundled script, so a
child theme that re-authors the templates with different hooks can ship its own
behavior.

```rst
.. doto-list::
   :format: kanban
   :status: open, in-progress, blocked
```

```rst
.. doto-list::
   :format: table
   :columns: id, title, status, priority, assignee
   :icon-mode: icon-text
```

### `.. doto-summary::` - Task Statistics

Displays task counts grouped by status/priority, optionally with a chart.

**Options:** `:group-by:`, `:assignee:`, `:show-chart:`, `:chart-type:`

`:chart-type:` accepts `bar`, `pie`, `stacked-bar`, `progress`, and `burndown`.
The engine is selected by `doto_chart_engine` (`svg` default, or `plotly`).

```rst
.. doto-summary::
   :group-by: status
   :show-chart: true
   :chart-type: pie
```

### `.. doto-archive::` - Archived Task Page

Renders all archived tasks, read directly from the JSON task store, with their
id, title, status, priority, assignee, archive date, original page, and body.
Takes no options. Used by the virtual archive page, but can be placed on any
page. See [Archiving and the Archive Page](#archiving-and-the-archive-page).

```rst
.. doto-archive::
```

### `:doto:` Role

Cross-reference to a task: `:doto:`TASK-001`` or `:doto:`TASK-001 <custom text>``

## Configuration

```python
# conf.py

# Core settings
doto_enabled = True
doto_include_done = True

# JSON store
doto_json_file = ".doto/tasks.json"
doto_auto_create_json = True

# Auto-archive
# Enabled by default: when a task reaches an archive status (see
# doto_archive_statuses) it is removed from its RST file, preserved in JSON,
# and shown on the archive page. Set to False to keep completed tasks inline.
doto_auto_archive = True
doto_archive_doc = "_doto_archive"
doto_archive_after_days = 0
doto_archive_statuses = ["done"]  # statuses that trigger archiving

# Sync settings
doto_sync_on_build = True
doto_conflict_action = "error"  # or "warn", "prefer-rst", "prefer-json"

# Defaults
doto_default_priority = "medium"
doto_default_status = "open"

# Display
doto_list_columns = ["id", "priority", "status", "assignee", "due", "title"]
# Task-list cell rendering: "icon" | "icon-text" | "text" (default "icon-text").
#   "icon"      = a Font Awesome icon where one fits the field/value (else text)
#   "icon-text" = icon + text
#   "text"      = text only
# Overridable per directive with :icon-mode:.
doto_list_icon_mode = "icon-text"

# Email view: default number of task rows kept visible at once in the
# scrollable top-right list pane. Overridable per directive with
# :visible-tasks:. Must be an integer >= 0; 0 means "show all" (no scroll cap).
# This caps the visible viewport only — all matching tasks still render and
# remain scrollable/clickable (distinct from :limit:, which caps how many
# tasks are included at all).
doto_list_visible_tasks = 5

# Charts
# Chart engine for doto-summary: "svg" (default) or "plotly".
#   "svg"    = built-in inline-SVG charts, no extra dependencies
#   "plotly" = renders static images via plotly + kaleido; falls back
#              automatically when plotly/kaleido/Chrome are unavailable
#              (inline SVG for HTML output, native TikZ charts for PDF/LaTeX)
# Requires the [charts] extra when set to "plotly".
doto_chart_engine = "svg"

# PDF/LaTeX task-box layout: "default" (roomy stacked-icon box) or "compact"
# (the same fields laid out densely: single-line header + inline icon+value
# pairs, tighter geometry). Overridable per directive with :latex-layout:.
# An unrecognized value falls back to "default". Fully backward compatible.
doto_latex_layout = "default"

# xlink resolution (optional)
# When True (default) and doxtr-xlink is installed AND listed in your
# extensions, the :assignee: field's value is scanned for :xlink:`key` tokens
# and each is resolved to the person/entity display name (and linked in
# HTML/PDF) at render time. Only the :assignee: field resolves today (title and
# body do not). The stored JSON/RST keep the raw token (sync stays byte-stable).
# Set to False to always render the raw token. Degrades gracefully when xlink is
# absent.
doto_resolve_xlinks = True

# Validation
doto_warn_overdue = True
doto_required_fields = []  # e.g., ["assignee"]
```

### CLI Configuration (`.doto.toml`)

```toml
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TASK"
default_priority = "medium"
default_status = "open"

# Current user for RACI auto-defaults (supports $VAR / ${VAR})
user = "$USER"

# Customize default columns for 'doto list'
list_columns = ["id", "title", "status", "priority", "assignee"]

# Valid values
statuses = ["open", "in-progress", "blocked", "done"]
priorities = ["low", "medium", "high", "critical"]

# TUI add-task modal: which fields the `a` modal shows (preset
# "minimal" | "default" | "all", or an explicit ordered list of field names).
# In an explicit list you may also include "repo" to position the repository
# picker (e.g. tui_add_fields = ["repo", "title", "due"]); presets keep the
# picker just under the title.
tui_add_fields = "default"

# TUI add-task modal: auto-select the newly created task after the `a` modal
# submits. When true (the default) the freshly added task becomes the
# highlighted row in whichever view is showing and is scrolled into view; set
# to false to keep the previous selection after adding a task.
tui_auto_select_new_task = true

# Recent-done filter (TUI filter/sort pop-up, `F`): the default window, in
# days, used to hide `done` tasks whose completion is older than N days (so the
# list stays focused on recent work). On by default; toggle it or change N in
# the pop-up and your choice is remembered across launches. Tasks completed
# before doto recorded completion timestamps are always shown. Default: 10.
tui_recent_done_days = 10

# Keep your work clock (working hours) OUT of a shared checkout. The global
# state file (work clock, active session, favorites, repo registry) is written
# to this private path instead of the shared .doto/config.json. Supports ~ and
# $VAR / ${VAR}; a relative path is anchored to the project base (the Sphinx
# source dir, which may be a `docs/` subdirectory -- not necessarily the repo root).
state_file = "~/private/doto-state.json"

# Per-field defaults prefilled in the TUI add-task modal. `due` accepts
# relative exprs ("tomorrow", "+7d", "friday"); `repo` matches a repo by name.
[doto.tui_add_defaults]
assignee = "alice"
due = "tomorrow"
```

The `state_file` setting also accepts a dedicated table form, and can be set
via the environment:

```toml
[state]
file = "~/private/doto-state.json"
```

> **Why this exists.** In a repo shared with your team, the global state file
> holds your **work clock** (clock-in/clock-out hours). If that file lives in
> (or is committed under) the shared tree, teammates can see your working
> hours. Pointing `state_file` at a personal location keeps your hours
> private. Resolution precedence is `$DOTO_CONFIG` → `state_file` /
> `DOTO_STATE_FILE` → portable `.doto/config.json` (found by walking up) →
> `~/.config/doto/config.json`. When `state_file` is unset, behaviour is
> unchanged.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DOTO_JSON_FILE` | Path to tasks.json |
| `DOTO_STATE_FILE` | Path to the private global-state file (work clock, active session, favorites, repo registry); overrides `state_file` |
| `DOTO_DEFAULT_PRIORITY` | Default priority for new tasks |
| `DOTO_DEFAULT_STATUS` | Default status for new tasks |
| `DOTO_USER` | Current user for RACI auto-defaults |
| `DOTO_LIST_COLUMNS` | Comma-separated list of columns for `doto list` |
| `DOTO_COLOR` | Color mode: `auto`, `always`, `never` |

### Remembered assignees and tags

doto remembers assignee names and tags you've used, so they're suggested in
future sessions. Whenever you set an assignee or a tag (via `doto add`,
`doto update`, or the TUI edit screen) the name is saved, so it is still
offered as a shell completion and as an auto-complete suggestion in the TUI
even after the original task is edited or deleted. Known names are stored in
`.doto/known_names.json` (next to `tasks.json`); the file is created
automatically and names are merged case-insensitively, so you never lose a
name you've typed before.

### RACI Roles

RACI (Responsible, Accountable, Consulted, Informed) lets you assign
project-management roles to people on each task.

**RST directive:**

```rst
.. doto:: Implement authentication
   :id: AUTH-001
   :raci: responsible alice, accountable bob, consulted carol, informed dave
```

The format is comma-separated `role name` pairs. Roles accept full names or
single-letter abbreviations (`r`, `a`, `c`, `i`), case-insensitively. Multiple
people per role are supported: `responsible alice, responsible bob`.

**CLI — adding a task:**

When adding a task, doto auto-sets the current user as both *Responsible* and
*Accountable*. This keeps task creation fast (no interactive RACI prompts).
The current user is resolved from (highest precedence first):

1. the `DOTO_USER` environment variable,
2. `[doto] user = "..."` in `.doto.toml` (supports `$VAR` / `${VAR}` env
   variable references),
3. `doto_default_user` in Sphinx `conf.py`,
4. `$USER` as a fallback.

To override the auto-default, pass `--raci` explicitly:

```bash
doto add "Fix login bug" --raci "responsible alice, accountable bob"
```

**CLI — updating RACI:**

The `--raci` flag on `doto update` *merges* with existing RACI data rather
than replacing it, so you can add roles incrementally:

```bash
doto update AUTH-001 --raci "consulted carol, informed dave"
```

**TUI:**

The edit screen (press `e e` on a task) shows four input fields — Responsible,
Accountable, Consulted, Informed — each accepting comma-separated names with
auto-complete from known assignees.

**Sphinx config (`conf.py`):**

Set `doto_default_user` for Sphinx builds (same env-var resolution as the
CLI):

```python
doto_default_user = "$USER"
```

**HTML rendering:**

In the task box (single-task view), RACI appears as a small subsection below
the assignee. In list columns, a compact summary like `R: alice, A: bob` is
shown. The HTML rendering is overridable: call
`doxtr_doto.raci.register_raci_html_renderer(fn)` with a custom
`(raci_dict) -> str` callable to replace the built-in markup.

In the **TUI card viewer popup** (`Enter` on a task), RACI is shown too, but
filtered: only the roles/names that *differ* from your configured default user
are displayed (a role assigned only to you is suppressed as the boring
default). See the TUI card viewer popup section below and the overridable
`doxtr_doto.raci.register_raci_differing_renderer`.

**Remembered names:**

People names used in RACI roles are automatically persisted as known assignees
(in `.doto/known_names.json`), so they appear in future completions.

## Resolving xlinks

If [`doxtr-xlink`](https://pypi.org/project/doxtr-xlink/) is
installed and listed in your `extensions`, doto resolves `:xlink:`key`` tokens
in the task `:assignee:` field to the referenced entity's display name at render
time, linking it in HTML and PDF output. Only the `:assignee:` field resolves
(the `:title:` and `:body:` fields render their raw text unchanged).

Before (raw token stored in your RST / `tasks.json`):

```rst
.. doto:: Document the decision
   :assignee: :xlink:`yourdirectory-person-alice-bobbington`
```

After (rendered HTML / PDF): the assignee shows **Alice Bobbington**, linked to the
URL from the matching `.xlink` entry
(`yourdirectory-person-alice-bobbington :: Alice Bobbington :: https://.../abobbington`). When a key
cannot be resolved, its bare key is shown instead.

Resolution is **render-time only** — the stored RST and `tasks.json` keep the
raw `:xlink:` token, so bidirectional sync stays byte-stable.

This is opt-outable and degrades gracefully:

- Set `doto_resolve_xlinks = False` to always render the raw `:xlink:` token.
- When `doxtr-xlink` is not installed (or not in `extensions`), doto
  renders the raw token unchanged — no crash, no warning spam.

Custom HTML templates for a single task (`doto.html`) and the cards list view
(`doto-list-cards.html`) receive the resolved assignee URL as an `assignee_href`
context variable (empty when there is no resolved link), so a theme can render
the assignee as a real `<a>`.

Install the optional dependency with the `xlink` extra:

```bash
pip install "doxtr-doto[xlink]"
```

## Command-Line Interface

```bash
# Initialize doto in a project
doto init

# Enable shell tab completion (bash, zsh, fish)
doto completion --install

# Show current configuration (JSON database path, mode, defaults)
doto config
doto config --format json

# Add a task
doto add "Fix authentication bug" --priority high --assignee alice

# List tasks
doto list --status open --format table
doto list --columns id,title,status,assignee  # custom columns
doto list --with-deps                         # show dependency info
doto list --format tree                       # tree view with deps

# Multi-repo views and namespaced task IDs
doto repos                        # list cached repositories
doto repos rescan                 # discover repos under cwd and cache them
doto repos rescan /path/to/src    # discover under a specific path
doto repos add /path/to/project   # add a single repo to the cache
doto repos forget web-app         # drop a repo from the cache
doto list -r                      # aggregated view across cached repos (repo#id when ambiguous)
doto list --rescan                # rediscover repos, then aggregate
doto done web-app#14              # act on a namespaced task from any directory
doto show web-app#14              # namespaced IDs work for show/update/start too
doto update web-app#14 --status in-progress

# Update a task
doto update TASK-001 --status in-progress
doto update TASK-001 --estimate 1h30m             # set a time estimate
doto update TASK-001 --clear-estimate             # remove the estimate

# Bulk update tasks with filters
doto update --filter-status open --priority high --all
doto update --filter-priority low --status blocked --all
doto update --filter-assignee alice --status done --all
doto update --filter-tags bug --add-tags urgent --all
doto update --filter-overdue --add-tags needs-attention --all
doto update --filter-status open --priority high --all --dry-run
doto update --filter-status open --status in-progress --all --yes

# Mark as done
doto done TASK-001
doto complete TASK-001                            # 'complete' is an alias of 'done'
# With auto-archive on (the default), marking a task done removes its directive
# from the RST file on the next Sphinx build and moves it to the archive page.

# Reopen archived tasks (restores the directive to its original place)
doto reopen TASK-001                              # re-insert at original location
doto reopen TASK-001 --status in-progress         # reopen with a specific status
doto reopen TASK-001 TASK-002                     # reopen multiple
doto reopen TASK-001 --file tasks/backlog.rst     # force a target file instead
doto reopen TASK-001 --json                       # JSON output
# If the original page was heavily modified, the directive is placed at the top
# of that page. If the original page was renamed/deleted, the reopen fails for
# that task with a message naming the original page title so you can retrace it.

# Time tracking: dual-layer work clock + per-task focus timers
doto start                        # clock in (start the global work clock)
doto start work                   # same as 'doto start'
doto start TASK-001               # auto clock-in, then start a focus timer
doto stop                         # pause the focus timer (work clock keeps running)
doto stop work                    # stop the focus timer AND clock out
doto clock-out                    # alias of 'doto stop work'
doto status                       # show active focus task + today's work clock
doto status --json                # machine-readable status

# Work report: break-aware work hours + a separate per-task/per-repo breakdown
doto report                       # today's gross / breaks / net work clock
doto report -p week               # this week
doto report -p month              # this month
doto report -p year --year 2026   # a specific year
doto report -p all                # all time
doto report --json                # machine-readable report
#
# Breaks are the real clock-out gaps you record during the day: when you are
# on break you are clocked out, so that gap is already excluded from gross and
# is shown as an explicit "break" (span + duration) rather than deducted a
# second time. A break taken at ANY time of day is handled correctly - e.g. a
# 12:55-13:34 break is NOT additionally charged a nominal lunch hour. A
# configured break only subtracts its nominal duration when you opt it into
# auto-deduction (the `auto` flag in the breaks modal), for people who work
# straight through without clocking out. By default nothing is ever
# double-counted.

# Daily worked-tasks timesheet (CSV): one row per worked interval - the global
# work clock AND each task's focus sessions - with times rounded to the nearest
# quarter hour, plus a final total row of the exact work-clock span.
doto timesheet                                   # today, to stdout
doto timesheet --date 2026-10-01                 # a specific day
doto timesheet -o sheet.csv                      # write to a file
doto timesheet --columns date,start_time,end_time  # minimal columns

# Session interval log + recovery of unclosed/overnight sessions
doto log TASK-001                 # list this task's work intervals (+ live row)
doto log                          # defaults to the active focus task
doto log TASK-001 --day 2026-01-15        # only sessions started on that date
doto log TASK-001 --fix close             # close an unclosed/overnight session now
doto log TASK-001 --fix split             # split an overnight session at midnight
doto log TASK-001 --fix discard           # drop an unclosed session (don't count it)
doto log TASK-001 --edit 2026-01-15T18:00:00+00:00  # set the open session's stop time

# Archive tasks (hide from listings, can reopen later)
doto archive TASK-001
doto archive TASK-001 TASK-002 TASK-003
doto archive TASK-001 --json

# Delete tasks permanently (DESTRUCTIVE - cannot be undone)
doto delete TASK-001                              # single task
doto delete TASK-001 TASK-002                     # multiple tasks
doto delete TASK-001 --force                      # skip confirmation
doto delete TASK-001 --dry-run                    # preview without deleting
doto delete --filter-status done --all            # delete all done tasks
doto delete --filter-archived --all               # delete all archived tasks
doto delete TASK-001 --json                       # JSON output

# Show next task to work on
doto next                         # suggests based on priority, due dates, deps
doto next --assignee alice        # filter by assignee
doto next --all                   # show top 5 ready tasks

# Show task dependency tree
doto tree                         # show all tasks as dependency forest
doto tree TASK-001                # show what TASK-001 depends on
doto tree TASK-001 -r             # show what depends on TASK-001
doto tree --compact               # minimal output (IDs only)

# Show task dependencies (tasks that must be completed first)
doto deps TASK-001                    # direct dependencies
doto deps TASK-001 --recursive        # include transitive dependencies
doto deps TASK-001 --pending-only     # only incomplete dependencies
doto deps TASK-001 --format tree      # tree visualization

# Search tasks
doto search "authentication"

# Show statistics
doto stats --by-status
```

### Recurring Tasks

Create recurring task series that automatically generate individual tasks:

```bash
# Create a weekly recurring task
doto add "Weekly review" --repeat "every friday" --until 2025-12-31

# Bi-weekly sprint planning
doto add "Sprint planning" --repeat "every 2 weeks on monday" --until +6m

# Monthly report on the last Friday (with date in title)
doto add "Monthly report {date}" --repeat "every month on last friday" --until +1y

# Quarterly review on the first Monday
doto add "Quarterly review" --repeat "every 3 months on first monday" --until +2y
```

**Start time, duration, and a custom start date.** A pattern may carry a
start time (`at HH:MM`) and a per-occurrence duration (`for <duration>`), and
`--from` / `-F` sets the series start date (instead of today):

```bash
# A 2-hour sync every other Monday at 16:00, starting 2026-11-01
doto add "Important Sync Meeting" \
    --repeat "every 2 weeks on monday at 16:00 for 2h" \
    --from 2026-11-01 \
    -u 2027-10-10

# Daily standup at 09:00 (no duration), starting next monday
doto add "Standup" --repeat "every day at 09:00" --from next-monday --until +1m
```

- `at <time>` accepts `16:00`, `16h`, or `16:00:31`; each generated task's
  `due` becomes a time-bearing `YYYY-MM-DDTHH:MM` so the calendar-sync and
  due-with-time features pick it up.
- `for <duration>` accepts `2h`, `90m`, `1h30m`, or a bare integer number of
  minutes (e.g. `90`); it sets each task's `estimate` (in whole minutes).
- `--from` accepts the same forms as any date (`2026-11-01`, `+1m`, `monday`,
  `next-monday`, ...). Without `--from` the series still starts today, and a
  pattern without `at` / `for` behaves exactly as before.
- `--from` and `--until` both require `--repeat`; `--until` must be after the
  resolved start date.

**Supported recurrence patterns:**

| Pattern | Example |
|---------|--------|
| Daily | `every day`, `every 3 days` |
| Weekly | `every friday`, `every 2 weeks on monday` |
| Monthly (day) | `every month on 15`, `every 2 months on 1` |
| Monthly (weekday) | `every month on first monday`, `every month on last friday` |
| Quarterly | `every 3 months on first monday` |
| With time | `every monday at 16:00` (adds a clock time to each `due`) |
| With duration | `every monday for 2h` (sets each task's `estimate`) |
| Time + duration | `every 2 weeks on monday at 16:00 for 2h` |

**Title templating:** Use `{date}` in the title to include the occurrence date (e.g., "Weekly review {date}" → "Weekly review Aug 7").

### Managing Series

```bash
# List all series
doto series list

# Show series details and all tasks
doto series show SER-001

# Mark all past tasks in a series as done
doto series complete SER-001

# Complete tasks before a specific date
doto series complete SER-001 --before 2025-08-15

# Extend a series with a new end date
doto series extend SER-001 +3m

# Update a series from a chosen occurrence forward (FORWARD-ONLY):
# re-stamp time/duration/title onto occurrences on or after the --from anchor.
# --from takes a task id (its due date is the anchor) OR a date.
doto series update SER-001 --from DOTO-002 --at 16:00 --for 2h
doto series update SER-001 --from 2026-08-15 --repeat "every 2 weeks on monday"
doto series update SER-001 --from DOTO-002 --title "Weekly sync {date}"

# Clear the per-occurrence start time / duration going forward:
doto series update SER-001 --from DOTO-002 --no-time --no-duration

# Update only the stored pattern/title (re-stamp no tasks):
doto series update SER-001 --metadata-only --at 09:00

# Preview without writing:
doto series update SER-001 --from DOTO-002 --for 90m --dry-run

# Delete a series and all its tasks
doto series delete SER-001

# Delete series but keep the tasks
doto series delete SER-001 --keep-tasks
```

**`doto series update` is FORWARD-ONLY.** The `--from` anchor (a task id or a
date) marks where the change begins: only occurrences whose due date is on or
after the anchor are re-stamped, and done/archived occurrences are skipped.
Occurrences *before* the anchor are never modified (even if in the past).
Changing the calendar *shape* (`--repeat`) only re-stamps time/duration/title
onto the **existing** forward dates — it does not move or add dates; use
`doto series extend` to add dates.

When viewing a task that's part of a series, the series info is displayed:

```bash
$ doto show DOTO-002
╭─ DOTO-002 - Weekly standup Jul 31 ───────────────────────────────────────────╮
│ Priority: medium                                                             │
│ Status: open                                                                 │
│ Due: 2026-07-31                                                              │
│ Tags: recurring, meeting                                                     │
│ Series: SER-001 (every friday, until 2026-08-28)                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### Multi-Repo Registry & Namespaced IDs

doto can aggregate tasks from multiple projects. A *repository* is any
directory containing a `.doto/tasks.json` store. The set of known repositories
is **cached** in the global config (`~/.config/doto/config.json`, respecting
`XDG_CONFIG_HOME`), so ordinary commands read the cache and only rediscover
when you ask.

```bash
# Discover repositories under the current directory and cache the result.
# Pruning skips .git, node_modules, target, .venv, dist, build, __pycache__
# and any directories matched by .gitignore files encountered along the way.
# A .doto repo nested inside another repo is also discovered: the walk keeps
# descending into non-pruned, non-gitignored children.
doto repos rescan

# Inspect / edit the cache without scanning the filesystem.
doto repos                 # list cached repositories
doto repos add /path/to/project
doto repos forget web-app

# Aggregated, multi-repo task view. IDs are shown bare when unambiguous, else
# namespaced as repo#id so they stay unambiguous across projects.
doto list -r
doto list --rescan         # rediscover first, then aggregate
```

When operating inside a single repository (local scope), task IDs are shown
bare (`14`). In aggregated/global views (`doto list -r`), each task's ID is
shown bare when its base prefix (the identifier with a trailing `-<number>`
stripped, e.g. `CALC` in `CALC-002`) belongs to only one repo in that view;
when two or more repos share a base prefix, every task in that group is shown
namespaced (`web-app#14`) to stay unambiguous. A namespaced ID can be used from
**any** working directory and is resolved against the cached registry; a bare
ID resolves against the current repository:

```bash
doto done web-app#14       # from anywhere, once web-app is cached
doto show web-app#14
doto update web-app#14 --priority high
doto start web-app#14      # start a focus timer for a task in another repo
```

### Daily Timesheet (CSV)

`doto timesheet` exports a CSV of everything you worked on during a single day,
suitable for pasting into a spreadsheet or a client/invoicing tool. Each **row
is one worked interval**:

- every interval of the global **work clock** for that day (`kind` = `work`), and
- every **task focus-session** interval for that day (`kind` = `task`),
  aggregated across every registered repository.

Start and end times are rounded to the **nearest 15-minute boundary** using a
midpoint rule: a time less than 7.5 minutes past a quarter rounds *down*, and
7.5 minutes or more rounds *up* (so `:07` → `:00`, `:08` → `:15`, `:43` → `:45`,
and `:45` stays `:45`). The rounding lives in a pure, overridable helper
(`doxtr_doto.work_report.round_to_quarter_hour`) so a child theme can swap in a
different granularity or tie-breaking rule.

The final `total` row reports the **exact, unrounded** work-clock span for the
day — from the earliest work-clock start to the latest work-clock stop
(including any mid-day gaps), formatted as `HH:MM`. This is the *work-clock
span*, deliberately **not** the sum of the individual task or interval times.

```bash
doto timesheet                                   # today, printed to stdout
doto timesheet --date 2026-10-01                 # a specific day (YYYY-MM-DD)
doto timesheet -o sheet.csv                      # write to a file
doto timesheet --columns date,start_time,end_time  # choose/reorder columns
```

Minimum-column example (`--columns date,start_time,end_time`):

```csv
date,start_time,end_time
2026-10-01,10:00,15:45
2026-10-01,16:00,18:15
2026-10-01,,08:15
```

(The last line is the `total` row; with this column subset the exact span lands
in `end_time`.)

#### Columns (`--columns`)

Pass a comma-separated list to `--columns` to choose and order the output
columns. Unknown names are rejected. The default is all of the following, in
this order:

| Column | Description |
|--------|-------------|
| `date` | The calendar date of the interval (`YYYY-MM-DD`) |
| `start_time` | Interval start, rounded to the nearest quarter hour (`HH:MM`) |
| `end_time` | Interval end, rounded to the nearest quarter hour (`HH:MM`) |
| `task_id` | The task identifier (empty for `work` rows) |
| `title` | The task title (empty for `work` rows; `Total work-clock span` on the `total` row) |
| `kind` | `work`, `task`, or `total` (the final row) |
| `duration` | Per-row rounded interval length (`HH:MM`); on the `total` row this holds the exact unrounded work-clock span |

A day with no worked time emits the header row only. Free-text cells (`title`,
`task_id`) that begin with a spreadsheet formula trigger (`=`, `+`, `-`, `@`, or
a leading tab/carriage return) are prefixed with an apostrophe so they are
treated as literal text and cannot auto-execute as a formula when the CSV is
opened in Excel/Sheets/LibreOffice (CSV formula-injection hardening). The
CSV-generation logic is kept as pure functions in `doxtr_doto.work_report`
(`timesheet_rows`, `work_span_seconds`, `timesheet_matrix`, `timesheet_csv`),
separate from the click command, so it is testable and a child theme can
subclass/replace it.

### CLI Commands Reference

| Command | Description |
|---------|-------------|
| `init` | Initialize doto in a project |
| `completion` | Set up shell tab completion (bash/zsh/fish) |
| `config` | Show current configuration (JSON path, mode, defaults) |
| `add` | Add a new task (supports `--repeat` for recurring tasks) |
| `list` | List tasks with filters and sorting (`-r`/`--recursive`, optionally `--rescan`, for multi-repo views) |
| `show` | Show details of a specific task |
| `update` | Update task fields |
| `done` | Mark tasks as done (auto-archives them on the next build when auto-archive is on) |
| `complete` | Alias of `done` |
| `start` | Clock in, or start a focus timer for a task (dual-layer) |
| `stop` | Pause the focus timer; `stop work` also clocks out |
| `clock-out` | Stop the focus timer and the work clock (alias of `stop work`) |
| `status` | Show the active focus task and today's work clock |
| `log` | List a task's session intervals; recover unclosed/overnight sessions |
| `repos` | List cached repositories; `rescan`/`add`/`forget` manage the registry |
| `next` | Show the next task to work on |
| `tree` | Display tasks as a dependency tree |
| `reopen` | Reopen archived tasks, restoring the directive to its original place (top-of-page fallback if the file changed; errors if the page was renamed/deleted) |
| `deps` | Show task dependencies (blocking tasks) |
| `series` | Manage recurring task series |
| `resolve` | Resolve merge conflicts between RST and JSON |
| `delete` | Permanently delete tasks (supports filters) |
| `archive` | Archive tasks (hide from listings, can reopen) |
| `export` | Export tasks to various formats (JSON, CSV, Markdown) |
| `search` | Search tasks by text pattern or regex |
| `stats` | Show task statistics |
| `report` | Report break-aware work hours + a separate per-task/per-repo breakdown |
| `timesheet` | Export a day's worked intervals (work clock + task sessions) to CSV |
| `tui` | Launch the interactive 3-pane terminal UI (requires the `tui` extra) |
| `calsync` | Sync tasks to a calendar (Google, Microsoft, Apple, CalDAV; requires the `calendar` extra) |

### Interactive TUI

`doto tui` opens an interactive, 3-pane terminal UI built on
[Textual](https://textual.textualize.io/). It is an **optional** feature; the
`textual` dependency is imported lazily so the core CLI works without it.
Install it with:

```bash
pip install 'doxtr-doto[tui]'
```

If `textual` is not installed, `doto tui` prints an install hint instead of
erroring out.

Layout:

- **Left pane** - the repository tree (from the cached registry), favorites,
  and a Global/Local scope indicator.
- **Upper-right pane** - the task list. Each row shows a running indicator
  (`▶` for an open worklog), a done checkbox (`[ ]` / `[✓]`), and
  priority/status/tag badges (reusing the CLI's priority and status colors).
- **Lower-right pane** - the selected task's details and an itemized session
  log (each `start → stop` interval with its duration, plus a live open row),
  stacked **below** the task list. Resize this split with `c d` (Config →
  Detail size); see the "Task-list layout views" section below.
- **Top-right elapsed display** - a right-aligned line showing the whole
  day's accumulated **work time** (summed across all of today's work-clock
  intervals) with the **current work session** - the time of the work-clock
  interval open right now - shown in parentheses after it (omitted when no
  session is open), plus the **total time spent on the currently highlighted
  task** (summed across all of that task's worklogs). It refreshes on the
  same live timer as the status line and updates immediately as you move the
  task-list cursor.
- **Status line** - two always-visible live counters, updated on a timer:
  the daily work clock (Layer 1) and the active focus session (Layer 2).

All mutations route through the **same functions the CLI verbs use**, so the
TUI never diverges from `doto add`, `doto done`, `doto start`, `doto stop`,
`doto clock-out`, and `doto repos rescan`.

Vim-style keybindings (with arrow-key equivalents). The TUI uses a **two-key
"stream" keymap**: related actions are grouped under memorable domain prefixes
(`e` edit, `s` state, `t` time, `c` config, `S` stats, `C` calendar sync). Pressing a
prefix repaints the bottom **hint bar** with that domain's sub-keys (newsboat-style `key:Label`
strip), so the scheme is self-documenting; `Esc` cancels a pending prefix and
`<prefix> ?` opens that domain's help.

> **Behavior change:** `e` is now a **prefix** (the Edit domain), not a flat
> edit key. Press `e e` to edit the selected entry. Within the Edit domain,
> **lowercase** second keys act on the single entry (`e e` edit, `e d` delete)
> and **uppercase** second keys act on the whole series (`e E` edit series,
> `e D` delete series). The series keys `e E` / `e D` — and the series-
> navigation keys `e n` / `e p` — appear **only when the
> selected task is part of a series**; for a standalone task the Edit domain
> shows just `e e` and `e d`.

Flat (single-press) keys:

| Key | Action |
|-----|--------|
| `j` / `k` (or `↓` / `↑`) | Move the task-list cursor down / up |
| `Shift+↑` / `Shift+↓` | **Jump to the top / bottom** of the current list. Table / list: first / last row. **Kanban:** the first / last card of the **current swim lane** (the move stays inside the focused status column — it moves the *selection cursor*, not the card, so switching lanes with `h` / `l` and jumping again lands on the first / last card of the now-current lane). **Calendar:** the active region's first / last entry (the first / last day of the visible month in the grid region, or the first / last task in the focused `Due` / `No due date` list). **Time:** the first / last day. A no-op on an empty list / lane |
| `Tab` | Cycle focus across the panes. Table layout: repo tree → task list → details. **Calendar:** cycle the view's regions and the details pane — month grid → `Due` task list → `No due date` task list → details → grid (so you can step from a selected day into its due / undated tasks). **Kanban:** move the selected card one swim lane **forward** (to the next status column — a status change), a no-op in the last column or into `(other)` |
| `Shift+Tab` | Cycle focus across the panes in **reverse** (the exact mirror of `Tab`). Table: repo tree → details → task list. Calendar: the region/details cycle walked in reverse. **Kanban:** move the selected card one swim lane **back** (to the previous status column), a no-op from the first column |
| `Space` | **Expand / collapse** the current row's sub-tasks when it is a parent (a ▾/▶ triangle like the repo tree); on a leaf row, **select / deselect** the task (multi-select) |
| `e` | **Edit domain prefix** (was a flat edit key — now press `e e` to edit). `e` arms the two-key **Edit** stream (see the stream table below): `e e` edits the selected entry, `e d` deletes it, and — only when the selected task is part of a series — `e E` edits the whole series from the selected occurrence forward and `e D` deletes the series |
| `a` | Add a task (modal over the existing add logic). The modal is **field-configurable** via `tui_add_fields` / `tui_add_defaults` (default = title + repo): choose a preset (`minimal` / `default` / `all`) or an explicit ordered field list. In an explicit list `repo` is an allowed orderable entry that positions the repository picker (e.g. `["repo", "title", "due"]`); in the presets the picker stays just under the title. Prefill fields (e.g. `due = "tomorrow"`, `repo` matched by name). It prompts for the configured fields **and** which repository to create the task in (a type-to-filter selector defaulting to the current repo; omitted when only the current repo is available). When a task is added into another repository, its id prefix and sequencing come from that repository's own `.doto.toml`, not the directory doto was launched in. After the task is created the list refreshes and, unless `tui_auto_select_new_task = false`, the new task is auto-selected (highlighted and scrolled into view) in whichever layout is active |
| `A` | **Calendar:** assign the selected calendar day as the highlighted `No due date` task's due date (routed through the single-task update logic). A no-op when no undated task is highlighted; a no-op in other layouts |
| `r` | **Add a recurring series** (modal over the same reusable series-build logic as `doto add --repeat`, so the TUI never diverges from the CLI). The dialog collects a title (supports `{date}`), a recurrence **pattern** (e.g. `every 2 weeks on monday`), an optional **start time** (`at`, e.g. `16:00`) and **duration** (`for`, e.g. `2h`), an optional **from** date (defaults to today), a required **until** date, and - when more than one repo is available - the target repository (defaulting to the current repo). Inputs are validated with the exact CLI parsers, so a bad pattern / time / duration / date keeps the dialog open with the error(s) shown. On submit the generated tasks get the time-bearing `due` and the `estimate` from the pattern, identical to the CLI |
| `w` | **Start / stop working** on the selected task(s): sets the doto **in-progress** and starts its focus timer in one press (a second press stops the timer and leaves the status unchanged). If the configured `statuses` have no `in-progress`, it gracefully degrades to timer-only. Honors the multi-selection |
| `d` | Mark the selected task(s) done (flat alias of `s d`) |
| `D` | Cycle the status of the selected task(s) (flat alias of `s n`) |
| `v` | Cycle the task-list layout (table → list → kanban → calendar → time) |
| `V` | Cycle the task-list layout in **reverse** (table ← list ← kanban ← calendar ← time), the exact mirror of `v` |
| `Enter` | **List / kanban / calendar:** open the card viewer popup (full task detail with a scrollable body; `Enter`/`Esc` close it, `e` opens the edit dialog). In the calendar's `Due` / `No due date` regions this is the highlighted task. **Table:** reveal the selected task's details (focus the details pane) |
| `h` / `l` (or `←` / `→`) | Kanban: **navigate the selection** to the previous / next swim lane (select a card in another status column, without changing any task). Calendar: select the previous / next day. Harmless no-op in the table / list layouts |
| `/` | Filter / search tasks (title, id, or tag) |
| `F` | Open the **filter & sort pop-up** (Feature below): hide completed tasks, hide `done` tasks completed more than N days ago (default 10), show only tasks due today / due this week, filter by a chosen tag or priority, filter by one or more **repositories**, and sort by due date / priority / tag / `next` (the recommended-next ordering) ascending or descending. The last choice is **remembered** across sessions |
| `R` | Rescan repositories |
| `g` | Toggle Global / Local scope (the TUI **defaults to Global**) |
| `?` | Open the top-level keybinding help (lists the flat keys and the stream domains) |
| `q` | Quit |

Stream (two-key) keys — press the prefix, then a sub-key:

| Stream | Action |
|--------|--------|
| `e e` | **Edit:** edit the selected entry (modal over the single-task update logic). `e` is now a prefix — a bare `e` no longer edits; press `e e` |
| `e d` | **Edit:** delete the selected entry (lowercase = single entry). Opens a yes/no confirm dialog; on confirm the task is deleted and, when it belonged to a series, pruned from that series' occurrence list |
| `e E` | **Edit:** edit the selected occurrence's **whole series from here forward** (uppercase = whole series). Shown **only when the selected task is part of a series**. The forward-only anchor is the selected occurrence's date: occurrences on / after it are re-stamped (time / duration / title), earlier ones are left unchanged. Routed through the same reusable `update_series` as `doto series update` |
| `e D` | **Edit:** delete the selected occurrence's **whole series** (uppercase = whole series). Shown **only when the selected task is part of a series**. Opens a confirm dialog offering **Delete series + tasks** / **Keep tasks, remove series** / **Cancel** (parity with `doto series delete` / `--keep-tasks`) |
| `e n` | **Edit:** jump to the **next** occurrence of the series (by due date). Shown **only when the selected task is part of a series**; clamps at the last occurrence (no wrap) |
| `e p` | **Edit:** jump to the **previous** occurrence of the series (by due date). Shown **only when the selected task is part of a series**; clamps at the first occurrence (no wrap) |
| `e P` | **Edit:** set parent — attach the selected entry (or the whole multi-selection) to a parent task picked from a pop-up. Always available (not series-only); the picker remembers the last chosen parent for quick repeat assignments. Rejects self/cycle parents and cross-repo parents (skipped with a notice) |
| `e ?` | **Edit:** open the edit-domain help |
| `s o` / `s i` / `s b` / `s d` | **State:** set the selected task(s) to open / in-progress / blocked / done. The sub-keys are **generated from the configured `statuses`** (first letter, lowercased); on a first-letter **collision** the later status takes its first unused letter from its own name (shown in the hint bar / help so the remap is never hidden) |
| `s n` / `s p` | **State:** cycle to the next / previous status (wraps) |
| `s ?` | **State:** open the state-domain help |
| `t t` | **Time:** toggle the focus timer (start / stop) on the selected task |
| `t o` | **Time:** clock out (stop the focus timer and the work clock) |
| `t w` | **Time:** manage work time (edit the work-clock intervals) |
| `t e` | **Time:** edit the **highlighted doto's recorded sessions** (add / edit / delete its focus-session intervals, persisted to that doto's owning repo store). A no-op in the `time` layout |
| `t ?` | **Time:** open the time-domain help |
| `c b` | **Config:** configure breaks + the work week (auto-deducted hours) |
| `c d` | **Config:** set the table-layout detail-pane size (how much of the height the detail pane takes, an `n/d` ratio of the total; applied live and persisted) |
| `c ?` | **Config:** open the config-domain help |
| `S w` | **Stats:** open the work-statistics pop-up (per-period net/gross/break numbers + text bar charts; `d`/`w`/`m`/`y`, `g`, `←`/`→`). Available from any layout; anchors on the time view's selected day when the time layout is active, otherwise on today |
| `S t` | **Stats:** open the per-doto time-reporting pop-up (worked time per doto / per repo as text bar charts; `d`/`w`/`m`/`y`, `g`, `←`/`→`). Available from any layout; anchors on the time view's selected day when the time layout is active, otherwise on today |
| `S ?` | **Stats:** open the stats-domain help |
| `C s` | **Calendar Sync:** sync **every displayed repository that has calendar sync enabled** (in Local scope: the current repo; in Global scope: all shown repos, narrowed by the active repo filter), each with its own `direction` / `conflict_policy` / calendar. Then refresh the task list. Mirrors `doto calsync sync` per repo. Runs in a background thread worker so the UI never freezes |
| `C p` | **Calendar Sync:** one-way **push** (doto → calendar). Mirrors `doto calsync push` |
| `C l` | **Calendar Sync:** one-way **pull** (calendar → doto), then refresh the view so imported/updated tasks appear. Mirrors `doto calsync pull` |
| `C t` | **Calendar Sync:** show the current config + a dry-run **plan** (create / update / delete / unchanged counts). Computed from the local store (no network), so it runs inline. Mirrors `doto calsync status` |
| `C i` | **Calendar Sync:** run the provider's interactive **login** (OAuth browser flow; CalDAV/Apple just verify the username/password). Mirrors `doto calsync login` |
| `C o` | **Calendar Sync:** clear the cached provider **token** (logout). Mirrors `doto calsync logout` |
| `C ?` | **Calendar Sync:** open the calendar-sync domain help |

The context-sensitive **hint bar** at the very bottom advertises the stream
prefixes plus a curated subset of flat keys when idle, and the pending
domain's sub-keys (ending with `?:Help  Esc:Cancel`) while a prefix is armed.
The stream prefixes are sticky: a pending prefix stays armed until a second
key, `Esc`, or any non-matching key clears it.

The arrow keys mirror the vim keys on **every** layout: `↓` / `↑` move the
cursor like `j` / `k`, and `←` / `→` drive the per-layout left/right move like
`h` / `l`. In the kanban layout `←` / `→` (and `h` / `l`) navigate the
selection across the swim lanes, while moving a *card* to another status
column is on `Tab` (forward) / `Shift+Tab` (back). `Shift+↑` / `Shift+↓` jump
the cursor to the first / last entry of the current list — in the kanban
layout this is the first / last card of the **current** lane, so it respects
whichever swim lane you have selected.

`Space` is split by the shape of the current row, mirroring how tree UIs
(including the repo explorer) treat it. On a **parent row** (one with
sub-tasks, marked by a ▾ expanded / ▶ collapsed triangle) `Space` toggles
whether that row's sub-tasks are shown; sub-tasks nest under their parent as a
fully recursive, indented tree (Parent → Child → Child-of-Child → … to any
depth), built from each task's `parent` link. On a **leaf row** (no sub-tasks)
`Space` toggles whether the current task is part of a multi-selection
(selected rows are marked in the task list). Parents start **expanded** so
new sub-tasks are visible by default, and the expand/collapse state is kept
for the current session (the tree nests in the **table** and **list** layouts;
the kanban and calendar layouts stay bucketed/graphical). When one or more
tasks are selected, `d` and `D` act on **all** selected tasks (completing or
cycling each), then clear the selection; when nothing is selected they act on
the single task under the cursor. `D` advances a task to the next status in
the configured cycle (`statuses`, defaulting to `open → in-progress →
blocked → done`), wrapping around at the end.

##### Task-list layout views (`v` / `V`)

Press `v` to cycle the task list between five layout views (analogous to the
`doto-list` directive's `:format:` views, but for the live terminal app), or
`V` (Shift+V) to cycle in **reverse** (the exact mirror of `v`). The
chosen layout is **persisted** to `~/.config/doto/config.json` (`tui_layout`),
so it becomes your default on the next launch. Older config files that predate
this field fall back to the default table view (backward compatible).

- **`table`** (default) - the 3-pane table described above: the repo tree on
  the left, and the task list stacked **above** the task-details pane on the
  right. Resize that vertical split with `c d` (Config → Detail size): type an
  `n/d` fraction for how much of the total height the **detail** pane takes
  (`3/4` the default gives the detail pane 3/4 and the list 1/4, `1/2` an even
  split, `1/4` a tall list with a glance of detail). The numerator must be a
  positive integer smaller than the denominator; any malformed, equal, or
  out-of-range value falls back to `3/4`. The chosen ratio is applied
  immediately and **persisted** to `~/.config/doto/config.json`
  (`tui_detail_ratio`), so it is restored on the next launch; older config
  files that predate this field fall back to the `3/4` default (backward
  compatible).
- **`list`** - a single compact column, one task per line. The highlighted
  row's details appear in the shared details pane as you move with `j` / `k`
  (or `↓` / `↑`); pressing `Enter` activates the highlighted row to reveal
  that task's details and move focus to the details pane, mirroring the table
  layout's Tab-to-details flow (routed through the app, like every other
  action). The list scrolls to keep the highlighted row in view as you move
  past the visible height.
- **`kanban`** - tasks grouped into columns by status (from the configured
  `statuses`), laid out **left-to-right** like a real board - every
  configured status is its own **side-by-side lane** (e.g. open │ in-progress
  │ blocked │ done render as four separate columns, never wrapping into a
  stacked 2x2 grid). The per-column width is derived from the available
  terminal width first (an even split across the lanes, floored at the
  minimum column width) so the whole board row always fits the viewport.
  Any task whose
  status is not in the configured list is shown in a trailing `(other)`
  column so nothing silently disappears. Each card is a framed, fixed-size
  **square tile** drawn with box-drawing characters: it is constrained in
  **both** width and height so it reads as an (approximately) square card
  rather than a variable-height block. Because a terminal character cell is
  about twice as tall as it is wide, a visual square uses roughly
  `width / 2` rows (tuned by the overridable `CARD_ASPECT`). The first
  interior line shows the task **ID and its due date** (a `(no due)`
  placeholder keeps the width stable when a task has none); when a task **ID**
  is too long to fit its lane it is **middle-truncated** - head and tail kept,
  the middle replaced by a single ellipsis (`ABCDEFGH-1234567` → `ABCD…4567`,
  via the overridable `truncate_id` / `ID_ELLIPSIS`) - rather than widening
  the column past the viewport or dropping the ID's (often disambiguating)
  tail. The
  description wraps underneath - **clipped with an ellipsis** (`…`) at the
  *end* (the body keeps end-clipping; only IDs use middle-truncation) when it
  does not fit, so a long body never makes the card grow. When the terminal
  is wide enough the card's **priority** is shown on the first line too, and
  the columns are **spaced evenly** across the available width; when space is
  tight the priority is dropped and the lanes narrow (middle-truncating long
  IDs) rather than wrapping. Every row is sized to its column so a card never
  **spills into the next column**. The currently selected card is marked by a
  highlighted **frame** (a colored border, via the overridable `frame_style`)
  rather than reverse-videoing the whole card body. The frame is drawn in the
  **active theme's accent colour** (the same hue the Textual footer uses for
  key labels like `tab`, and the same accent the title bracket highlight uses):
  the live app resolves the theme accent to a **concrete hex at render time**
  and publishes it onto the overridable `SELECTED_FRAME_ACCENT` class
  attribute, which `frame_style` prefers. (Console markup cannot reference
  Textual CSS theme *tokens* such as `$accent` directly - those resolve only in
  CSS - so the accent is resolved to a concrete hex first, exactly as the title
  bracket highlight does.) When no accent is published (pure-logic callers, or
  a theme with no accent) the frame falls back to the theme-safe
  **reverse-video** `SELECTED_FRAME_STYLE = "bold reverse"`, which swaps the
  theme's own foreground and background so the selected card's frame stays
  visible on every built-in theme (light **and** dark). Both the accent and the
  fallback remain overridable class attributes (child-theme seam). The **active
  (focused) lane** is additionally shown by coloring its column **header** and -
  when the lane
  holds no card - its `(empty)` placeholder (via the overridable
  `ACTIVE_COLUMN_STYLE` / `format_header` / `format_empty_placeholder`), so the
  active lane is always visible even when it is empty and has no highlighted
  card frame to mark it. The active-lane highlight is drawn with
  **reverse-video** (`ACTIVE_COLUMN_STYLE = "bold reverse"`), which swaps the
  theme's own foreground and background into an inverted block behind the lane
  name. Reverse-video is used because it is the most robust cross-theme
  highlight for an active element - it reuses the theme's contrast-guaranteed
  fg/bg pair, so the active lane name (e.g. `Open`) stays clearly delineated on
  every built-in theme, including the light themes where a fixed hue such as
  the former `cyan` was effectively invisible. The coloring is pure markup
  that occupies no screen
  columns, so it never changes a column's computed width or the board
  alignment. Pressing `Enter` on a card
  opens a **card viewer popup** (see below). Because terminal drag-and-drop
  is not practical, moving a card between columns is done with the keyboard:
  `Tab` moves the selected card to the **next** status column (one lane
  forward) and `Shift+Tab` moves it to the **previous** column (one lane
  back) — the **terminal drag-equivalent** of dragging a card — which
  changes its status through the same `doto update` code path as every other
  mutation. The move is a no-op in the last/first real column or into the
  `(other)` column (no wrap). Navigating the *selection* across lanes without
  moving a card is on `h` / `l` (or `←` / `→`), which refreshes the details
  pane for the newly selected card. The board scrolls to keep the highlighted
  card visible.
- **`calendar`** - a month grid placing tasks on their due date; days with
  tasks due are highlighted. The view has three **focus regions** cycled with
  `Tab` (and the exact reverse with `Shift+Tab`): the **month grid**, the
  **`Due <date>` task list** for the selected day, and the always-shown
  **`No due date` task list**, followed by the shared details pane and back to
  the grid. In the grid region `h` / `l` (or `←` / `→`) select the previous /
  next day and `j` / `k` (or `↑` / `↓`) move a whole week; in the `Due` /
  `No due date` regions `j` / `k` move the per-task cursor (and flowing past a
  list's end advances to the adjacent region). A highlighted task in the `Due`
  or `No due date` region is what `Enter` reveals and `e` edits, so you can
  step from a selected day straight into its due tasks (or the undated bucket)
  to view / edit / close them. The **month grid stays pinned** at the top -
  grid navigation only ever moves the selector within the grid, so the grid
  header and week rows never scroll off. The per-day task list rendered below
  the grid is reached by `Tab` (into the `Due` / `No due date` regions) or by
  the container's own scroll (mouse wheel / scrollbar) when it is tall.
  Pressing `A` while a `No due date` task is highlighted **assigns the
  selected calendar day** as that task's due date (routed through the
  single-task update logic, so the mutation never diverges from `doto
  update`); the task then leaves the undated bucket and appears under that
  day's `Due` list. Tasks with no (or an unparseable) due date are collected
  into the always-shown `No due date` bucket, so undated tasks never crash the
  view.
- **`time`** - a time-management view of the global **work clock** (not the
  task list): every day that has one or more work-clock intervals, newest
  first, each listing its start/stop intervals and that day's **gross /
  break / net** totals, with a **grand total** across all shown
  days pinned at the top. Breaks here are the **real clock-out gaps** you
  recorded during the day (the explicit time you were clocked out mid-day),
  surfaced as what actually happened rather than a nominal auto-deduction;
  the math reuses the same `doto report` logic, so the net figures agree with
  the CLI report. `j` / `k` (or `↓` / `↑`) move
  the day cursor; pressing `Enter` opens the **work-time manager** (the same
  modal as `t`) for the selected day so you can add / edit / delete that day's
  intervals, and the totals update on close. This is the read-oriented
  companion to the `t` modal. To the **right** of the day list sits a
  **summary panel** showing the gross / breaks / **net** totals for **This
  week**, **This month**, and **This year** (each anchored on today, reusing
  the same `work_report.compute_period` math), plus a configurable **Work
  week** net total (the sum of net work over the current week's days whose
  weekday is in your configured work-week set, defaulting to **Mon–Fri**).
  The work-week set uses Python's Monday=0..Sunday=6 convention, is stored as
  `workweek_days` in the global config, and is editable from the **breaks +
  work week** modal (`b`): enter it as `Mon-Fri` or `0,1,2,3,4` (a contiguous
  run renders as `Mon–Fri`; otherwise the weekdays are listed). The same
  modal edits the recurring breaks: each break row is
  `name,HH:MM,duration[,leeway[,auto]]`, where the optional `auto` column
  (`yes`/`no`, default `no`) opts the break into legacy auto-deduction. The panel
  refreshes automatically whenever intervals (or the work-week set) change
  (e.g. after the work-time manager or breaks modal closes). The
  summary panel is an overridable `WorkTimeSummary` widget
  (`DotoApp.work_time_summary_class`) with pure `format_*` classmethods (incl.
  a separate `format_workweek` seam for the work-week line) so a child theme
  can replace its rendering. Pressing **`S`** in this layout opens
  a **statistics pop-up**: a modal showing per-period numbers *and* text /
  ASCII block-character bar charts (not the SVG `charts.py` renderer). It
  defaults to the **day work length distribution per week** (one `█` bar per
  weekday showing that day's net length) and switches granularity with
  `d` / `w` / `m` / `y` (or `g` to cycle day → week → month → year), moving the
  anchor period with `←` / `→`; each granularity also shows the period's net
  total as numbers. The pop-up is an overridable `WorkStatsScreen`
  (`DotoApp.work_stats_screen_class`), and its bars are drawn by the pure,
  unit-testable `render_bar_chart` helper. Pressing **`T`** in this layout
  opens a **per-doto time-reporting pop-up**: a modal showing, for a chosen
  granularity (`d` / `w` / `m` / `y`, or `g` to cycle, with `←` / `→` moving
  the period across years), **how long you worked on which dotos** - each
  doto's total focus-session time (sorted descending, as a text `█` bar chart)
  plus the **per-repository** totals, aggregated across every registered
  repository. It reuses the same `work_report.compute_task_breakdown` math and
  the shared cross-repo task collector that `doto report` uses, so the figures
  agree with the CLI; it is an overridable `TaskTimeStatsScreen`
  (`DotoApp.task_time_stats_screen_class`). Separately, pressing **`E`** on the
  **highlighted doto** (in the table / list / kanban / calendar layouts) opens
  a **per-doto session editor** that lists that single doto's recorded focus
  sessions (start → stop with per-interval and total duration) and lets you
  **add** (`a`), **edit** (`e` / `Enter`), or **delete** (`x`) a session,
  persisting the change back to that doto's owning repository store (reusing
  the same `apply_interval_edit` / `remove_interval` primitives and the
  **Edit work interval** pop-up as the work-time manager). It is an overridable
  `TaskSessionsScreen` (`DotoApp.task_sessions_screen_class`). In the
  **work-time manager** (`t`, or `Enter` on a day), the interval list is
  focused on open so `↑` / `↓`
  (or `j` / `k`) navigate between a day's sessions and `e` / `Enter` edit the
  highlighted one — including the 2nd and later intervals of a day, which
  previously could not be selected or edited. The **Edit work interval**
  pop-up (opened to add or edit an interval) shows a live **Duration** field
  that recomputes `stop − start` on every keystroke in the start/stop inputs
  (e.g. nudging the stop time updates `1h42m` → `1h57m` instantly). A blank
  stop shows `(running)` and an unparseable or non-positive duration shows a
  dim `—` placeholder; the actual save is still validated separately.

Across every layout, `Enter` acts on the currently selected task
(a harmless no-op when nothing is selectable). In the **list**, **kanban**,
and **calendar** layouts
`Enter` opens a **card viewer popup** - a modal listing the task's *full*
content (the same fields as `doto list -f cards`: id, title, assignee,
priority, status, due, tags, depends_on, series, created, updated, and body).
The style-markup field lines **wrap** so long titles/values are fully readable,
and the task **body renders as Markdown** (headings, lists, bold/italic, code)
in a **full-height, scrollable** region that fills the modal down to the hint
line so a long description scrolls inside
the popup. Pressing `Enter` again or `Escape` closes it; pressing `e` closes
the popup and opens the **edit dialog** for the same task (reusing the
`doto update` write and refreshing the board). In the **table** layout `Enter`
reveals the details in the shared details pane.

Beyond the shared `doto list -f cards` fields, the popup adds two **TUI-only**
fields (they appear only in this viewer, never in the CLI card):

- **RACI (differing from your default user).** Only the RACI roles/names that
  *differ* from your configured default user (`user`, falling back to
  `default_assignee`) are shown. A role assigned only to you is the boring
  default and is suppressed, so the popup surfaces just the people worth
  noticing. Remaining entries are grouped by role with their R/A/C/I labels
  (e.g. `RACI Consulted: carol`). The comparison is case-insensitive, matching
  the project's name-dedup policy. Overridable via
  `doxtr_doto.raci.register_raci_differing_renderer(fn)` with a
  `(raci_dict, default_user) -> list[str]` callable.
- **Time spent.** How long work has been clocked on the task, summed from its
  worklogs and formatted like `1h02m03s`. An **active (running) session**
  counts up to "now", so the value reflects a live session. The line is
  omitted when no time has been tracked (rather than showing `0s`).
  Overridable via `doxtr_doto.cli.session.register_time_spent_renderer(fn)`
  with a `(worklogs, now=None) -> str | None` callable.

The
`list` and `kanban` views scroll so the highlighted row stays visible as the
cursor moves (the `calendar` grid stays pinned, as noted above). Scrolling is
**smart**: during continuous `j` / `k` navigation the view only starts
scrolling once the
cursor comes within a small margin of the top or bottom of the visible frame,
and then jumps a block of rows in the direction you are moving rather than
creeping one line at a time. Both the margin (default `2` rows) and the jump
(default `5` tasks) are overridable class attributes on the shared
`AltLayoutView` - `SCROLL_MARGIN` and `SCROLL_JUMP` - so a child theme can tune
the feel by subclassing a view (or the base) and setting them.

After a **discontinuous** selection change the view instead *repositions* so
the whole selected task is always brought back on screen, with no direction
guess: switching swim lanes (`h` / `l`), selecting a task by id, or cycling
the layout (`v` / `V`) all guarantee the selected doto is visible. For example,
switching from the bottom of a long `open` lane to a one-card `in-progress`
lane scrolls the viewport back up so the single card is in view. This
reposition is the overridable `ensure_cursor_visible` seam on `AltLayoutView`;
the `calendar` overrides it to keep its month grid pinned to the top (cycling
into the calendar layout keeps the grid header on screen, and a calendar day
move reaches its scroll through the subsequent rebuild rather than this seam),
so a child theme can retune the discontinuous-jump behavior alongside
`SCROLL_MARGIN` / `SCROLL_JUMP`.

Each view is its own overridable widget class with pure `format_*`
classmethods, sharing an `AltLayoutView` base (the alt-view contract the app
drives through a single data-driven registry) and registered on `DotoApp` via
`list_view_class`, `kanban_view_class`, and `calendar_view_class`. A child
theme can replace any view's rendering by subclassing `DotoApp` and swapping
the attribute, mirroring the existing pane/screen seams.

##### Active (time-recorded) task always on top

The currently **active** task - the one with an open worklog session (started
with `s`) - is always pinned to the **top** of its list in *every* layout:
the top row of the table and list, the top card of its status column in the
kanban board, and the top of its day's list (and the undated bucket) in the
calendar. The pin is **stable** (non-running tasks keep their relative order,
and if several tasks are running they keep theirs) and is applied **after**
any sort, so the active task stays on top regardless of the chosen sort order
below. It is a small pure helper (`pin_active_first`) that each view applies
where it builds its rows, so a child theme can override it.

##### Filter & sort pop-up and sort memory (`F`)

Press `F` to open a modal pop-up that configures how the task list is filtered
and sorted:

- **Filters:** hide completed (`done`) tasks, hide stale `done` tasks - those
  completed more than N days ago (the **recent done** filter, **on by
  default** with N from the `tui_recent_done_days` config key, default 10;
  undated / legacy `done` tasks that carry no completion timestamp are always
  shown) - show only tasks due **today**,
  show only tasks due **this week** (today through the coming Sunday), show
  only tasks carrying a chosen **tag** (from the known tags), show only
  tasks with a chosen **priority**, and show only tasks from one or more
  selected **repositories** (a multi-select, meaningful in Global scope).
- **Sort by** (single select) with an ascending / descending **order**: due
  date, priority, tag, or **`next`** - the recommended-next ordering, which
  reuses the exact `doto next` scoring (in-progress bonus, priority, due-date
  urgency, dependency penalties) rather than duplicating it, so the TUI's
  "next" order matches the CLI.

**Filtering by repository.** The TUI now defaults to **Global** scope (press
`g` to toggle Global / Local). You can restrict which repositories' dotos are
shown either in the `F` pop-up's **Repositories** multi-select *or* by
selecting repository leaves in the **repo tree** (the left pane of the table
view) - selecting a repo there toggles it in the same filter and marks it with
a leading check. The selection semantics are:

- **Local** scope: only the current repository's dotos are shown (any repo
  filter selected in Global scope is ignored while in Local).
- **Global** scope with **no** repositories selected: dotos from **all**
  repositories are shown.
- **Global** scope with **one or more** repositories selected: only the dotos
  from the **selected** repositories are shown.

The filter / sort composition order is: gather → free-text `/` filter → the
`F` pop-up's filters (including the repo filter) → its sort → **pin the active
task to the top**. Each step is a separate overridable call.

The last filter **and** sort state is **remembered** across sessions: it is
persisted to `~/.config/doto/config.json` (the `tui_hide_completed`,
`tui_recent_done_enabled`, `tui_recent_done_days`, `tui_due_filter`,
`tui_tag_filter`, `tui_priority_filter`, `tui_sort_key`,
`tui_sort_order`, and `tui_repo_filter` fields) and restored on the next
launch. Older config files that predate these fields fall back to no filter
and no sort (backward compatible). The pop-up is its own overridable screen
(`DotoApp.view_prefs_screen_class`, with the repository multi-select widget
overridable via `repo_select_class`), and the pure filter / sort helpers live
in `doxtr_doto.cli.tui.filtersort` so a child theme can swap either.

##### Theming and UTF-8

The TUI uses Textual's built-in themes. Open the **command palette** with
`Ctrl+P` and pick a theme (e.g. `tokyo-night`, `dracula`, `nord`, `gruvbox`,
`ansi-light`/`ansi-dark`, `textual-light`/`textual-dark`, `solarized-light`);
the choice applies live. All of the TUI's highlights are **theme-aware** so
they stay legible on every built-in theme, light and dark:

- The **active kanban lane** header uses reverse-video
  (`KanbanView.ACTIVE_COLUMN_STYLE = "bold reverse"`), which swaps the theme's
  own foreground and background, so the active lane name stays visible on light
  themes - fixing the earlier case where a fixed `cyan` highlight was invisible
  on a light background. Reverse-video is used (rather than a Textual CSS theme
  token like `$accent`) because console markup resolves only Rich styles, not
  CSS design tokens. It remains an overridable class attribute (child-theme
  seam).
- The **selected card frame** is drawn in the active theme's **accent colour**
  (the hue the Textual footer uses for key labels like `tab`, the same accent
  the title bracket highlight uses): the live app resolves the accent to a
  **concrete hex at render time** and publishes it onto the overridable
  `KanbanView.SELECTED_FRAME_ACCENT` class attribute, which `frame_style`
  prefers (the accent must be a concrete hex - not a `$accent` CSS token, which
  console markup cannot resolve). When no accent is published it falls back to
  the theme-safe reverse-video
  `KanbanView.SELECTED_FRAME_STYLE = "bold reverse"`,
  so the selected card stays visible on every built-in theme. Both
  the accent and the fallback remain overridable class attributes (child-theme
  seam).
- The card-viewer **Markdown headers** derive their colors from
  contrast-tuned `$text-*` theme tokens (applied via the viewer's **CSS**,
  where theme tokens are valid), so headings stay readable and mutually
  distinct on every theme.
- Other markers (repo-tree "here" marker, calendar day-with-tasks) use
  reverse-video; the status/focus counters and time view use valid Rich named
  colors (`cyan` / `magenta` / `green`). None embed a CSS theme token in
  console markup.

`doto tui` forces `stdin` / `stdout` / `stderr` to **UTF-8** before launching
so German umlauts (ä ö ü Ä Ö Ü ß), box-drawing card frames, and status glyphs
(▶ ✔ ⏱) render correctly even on a non-UTF-8 locale (e.g. `LANG=C`), without
depending on your `LANG` / `PYTHONIOENCODING`. If a stream cannot be
reconfigured (e.g. under capture or a redirected pipe) it is left untouched.

##### Edit dialog (`e`)

The edit dialog pre-populates the selected task's fields. Three conveniences
speed up editing:

- **Type-to-filter Priority / Status** - while the Priority or Status field is
  focused, typing letters narrows and/or selects a matching option. Matching
  is *word-based*: each option is split on separators (e.g. `-` or spaces)
  into words, and a word that starts with what you typed (case-insensitive)
  matches. So typing `progress` finds `in-progress`, and typing `c` in
  Priority selects `critical`. If exactly one option matches it is selected
  immediately; if several match the dropdown narrows to just those; `Backspace`
  shortens the query and `Escape` still cancels the dialog. The pure matching
  helper (`doxtr_doto.cli.tui.app.filter_options`) is unit-testable, and the
  control itself is an overridable `FilterableSelect` widget.
- **Scrolling, wrapping Body** - the Body field is a multi-line text area that
  soft-wraps at the right edge and scrolls when the content exceeds its
  height. Pressing `Enter` in the Body inserts a newline rather than
  submitting; the `Save` button is docked at the bottom of the dialog so it
  stays visible while you scroll. `Escape` cancels without saving.
- **Editable due date** - the dialog includes a Due field that accepts the
  same absolute (`YYYY-MM-DD`) and relative (`+7d`, `+2w`, `today`, `friday`,
  `next-monday`, ...) forms as `doto update --due`, parsed with the very same
  helper so the CLI and TUI never diverge. An optional clock time may be
  appended to any form (`friday 16:00`, `+2d 16h`, `2026-08-15T16:00`); see
  [Due dates with time](#due-dates-with-time). Leaving it empty clears the due
  date. An invalid date is reported inline and keeps the dialog open rather
  than writing a corrupt value to the store. The edit persists through the
  same code path as `doto update`, preserving RST↔JSON sync.
- **Editable estimate** - the dialog includes an Estimate field (below Due)
  that accepts the same compact duration syntax (`5m`, `90m`, `4h`, `1h30m`,
  or a bare number of minutes) as `doto update --estimate`, parsed with the
  very same `parse_duration` helper so the CLI and TUI never diverge. The
  field is pre-populated from the stored estimate rendered back to compact
  form (`90` shows as `1h30m`). Leaving it empty clears the estimate. An
  invalid value is reported inline and keeps the dialog open rather than
  writing a corrupt value to the store.
- **Bash-style kill / yank** - every text field in the dialog (Title,
  Assignee, Tags, and the Body) shares a single kill ring. `Ctrl-K` deletes
  from the cursor to the end of the line and captures the removed text;
  `Ctrl-Y` yanks (re-inserts) it at the cursor. Because the ring is shared,
  text killed in one field can be yanked into another - e.g. kill the Title
  with `Ctrl-K` and paste it into the Body with `Ctrl-Y`, or vice-versa. An
  empty kill at end-of-line leaves the buffer untouched. The input and
  text-area widgets are overridable via `EditTaskScreen.input_class` and
  `EditTaskScreen.text_area_class`.

#### Daily kickstart nudge

On launch, `doto tui` runs a once-per-day startup check. If you have **not**
been prompted yet today *and* no focus timer is currently running, it shows a
small kickstart modal to help you get going:

- `1`..`3` - start a focus timer on one of the top-priority candidate tasks
  (ranked with the same scoring as `doto next`, aggregated across your
  registered repositories; dependency penalties are applied per repo, so a
  task blocked by a pending same-repo dependency is deprioritized).
- `w` - clock in to general work (Layer-1 work clock, no specific task).
- `/` - open the search/filter modal.
- `esc` - skip for today.

**Any** choice (including skip) records today's date in
`~/.config/doto/config.json` (`last_prompt_date`), so the nudge fires at most
once per day. The decision logic lives in a small, unit-testable module
(`doxtr_doto.cli.tui.nudge`) separate from the modal widget.

Rendering is modular: the widget classes (`RepoTree`, `TaskList`,
`TaskDetails`, `StatusLine`) expose `format_*` classmethods and can be
subclassed, and `DotoApp` exposes `*_class` attributes so a child app can
replace any pane without rewriting the application. The modal screens are
likewise swappable through `edit_task_screen_class` and
`card_viewer_screen_class` (the kanban card viewer popup), and the kanban
card's square-tile layout and selected-frame styling are pure, overridable
`KanbanView` classmethods / class attributes. The lanes are always laid out
**side by side** (the per-column width comes from the available viewport
width, floored at `MIN_COLUMN_WIDTH`, so the board never wraps into a grid),
and over-long task **IDs are middle-truncated** to fit a lane via the pure,
overridable `truncate_id` classmethod and its `ID_ELLIPSIS` knob - a child
theme can restyle ID shortening alone without touching the layout math. Tune
the dimensions and styling
without rewriting a method via the class attributes `CARD_ASPECT`,
`MIN_CARD_ROWS`, `MAX_CARD_ROWS`, `MIN_COLUMN_WIDTH`, `FRAME_CHARS`,
`SELECTED_FRAME_STYLE`, `SELECTED_FRAME_ACCENT`,
`FRAME_STYLE`, `CLIP_INDICATOR` and `ID_ELLIPSIS`, or override the classmethods
`card_interior_rows`, `card_height`, `frame_overhead`, `frame_style`,
`truncate_id` and
`clip_body` for finer control. The card viewer derives its detail fields from
the single shared builder `doxtr_doto.cli.output.build_task_detail_lines` (the
same one the CLI `doto list -f cards` card uses), so a new task field appears
in both surfaces without editing two renderers. The viewer splits that output
into wrapped style-markup field lines (`build_field_lines`) and a Markdown body
widget; a child theme can swap the body's Markdown widget via
`CardViewerScreen.markdown_class`, reshape the body source with
`build_body_markdown`, or replace the body widget entirely with
`build_body_widget`. The body's **Markdown headers are styled from theme
tokens, not hardcoded colours**: the `#viewer-md` rules in `DotoApp.CSS` colour
`MarkdownH1`..`MarkdownH6` from the contrast-tuned `$text-*` tokens
(`$text-accent` / `$text-secondary` / `$text-error` for H1/H2/H3, `$text` for
h4-h6) so headings stay readable and visually distinct on every built-in theme
(light/dark/ansi) - the earlier bug where a dark-theme H3 rendered an invisible
dark navy. A child theme can re-style them by overriding those `#viewer-md`
rules in its own `CSS`. The popup's two **TUI-only** extra fields (RACI
differing from your default user, and the task's `Time spent`) are assembled by
the overridable `CardViewerScreen.build_extra_field_lines` instance method
(threaded with the resolved default user) and render into `#viewer-detail`
after the shared field lines; their renderers are independently swappable via
`doxtr_doto.raci.register_raci_differing_renderer` and
`doxtr_doto.cli.session.register_time_spent_renderer`.

### Filter Options Reference

Several commands (`list`, `update`, `delete`) support common filter options:

| Option | Short | Commands | Description |
|--------|-------|----------|-------------|
| `--status` | `-s` | list | Filter by status (comma-separated) |
| `--priority` | `-p` | list | Filter by priority (comma-separated) |
| `--assignee` | `-a` | list | Filter by assignee (comma-separated) |
| `--tags` | `-t` | list | Filter by tags (comma-separated, matches any) |
| `--filter-status` | | update, delete | Filter by status (comma-separated) |
| `--filter-priority` | | update, delete | Filter by priority (comma-separated) |
| `--filter-assignee` | | update, delete | Filter by assignee (comma-separated) |
| `--filter-tags` | | update, delete | Filter by tags (comma-separated) |
| `--filter-overdue` | | update | Filter only overdue tasks |
| `--filter-archived` | | delete | Only include archived tasks |
| `--archived` | | list, search, export, stats | Include archived tasks |

**Safety flags for bulk operations:**

| Flag | Description |
|------|-------------|
| `--all` | Required when using filters without specific task IDs (safety measure) |
| `--dry-run` | Preview which tasks would be affected without making changes |
| `--yes` / `-y` | Skip confirmation prompt for bulk updates |
| `--force` / `-f` | Skip confirmation prompt for delete |

### Shell Completion

Tab completion is available for bash, zsh, and fish. It completes:
- Task IDs (with status and title hints)
- Series IDs (with title hints)
- Assignee names (from existing tasks)
- Tags (from existing tasks)
- Status values (`open`, `in-progress`, `blocked`, `done`)
- Priority values (`low`, `medium`, `high`, `critical`)
- Due date shortcuts (`today`, `tomorrow`, `+1w`, `friday`, `next-monday`, `end-of-month`, etc.)
- Recurrence patterns (`every friday`, `every month on first monday`, etc.)

```bash
# Install permanently (auto-detects your shell)
doto completion --install

# Or enable for current session only
eval "$(doto completion bash)"   # bash
eval "$(doto completion zsh)"    # zsh
doto completion fish | source    # fish
```

## Calendar Sync

doto can push tasks that have a **due date** to an external calendar so your
deadlines show up alongside your meetings. It is an **optional** feature behind
the `calendar` extra:

```bash
pip install 'doxtr-doto[calendar]'
```

Supported providers:

| Provider | `provider =` | Auth |
|----------|--------------|------|
| Google Calendar | `google` | OAuth2 (browser login once per machine) |
| Microsoft 365 / Outlook | `microsoft` | OAuth2 (browser/device login) via Microsoft Graph |
| Apple iCloud | `apple` | CalDAV with an **app-specific password** |
| Generic CalDAV (Fastmail, Nextcloud, …) | `caldav` | CalDAV basic auth (username + password) |

> **Direction:** doto supports both **push** (doto → calendar) and
> **two-way** (calendar ↔ doto). Set `direction = "push"` (the default) for
> one-way push, or `direction = "two-way"` to also pull calendar events into
> doto. See [Two-way sync](#two-way-sync-calendar--doto) below.

### How tasks become calendar entries

Each task with a `:due:` is projected to one calendar item. doto owns only the
items it creates (they carry a stable `doto-<id>@doxtr-doto` UID), so it never
touches events you or other tools created.

> **Google note — automatic recovery from a reserved identifier.** Google
> Calendar keeps an event's UID reserved even after the event is deleted (it
> lingers as a hidden *cancelled* tombstone). If a task id is reused after its
> event was deleted, a fresh push would otherwise fail with a `409 "identifier
> already exists"`. doto self-heals this transparently — it resurrects/overwrites
> the existing item (via Google's `events.import`, falling back to an update)
> instead of failing the sync, so the task simply re-adopts its calendar item.
> This is specific to Google; the other providers are unaffected.

- **`event_mode = "event"` (default)** — the task becomes a **VEVENT** visible
  in the calendar grid:
  - A due **with a time** (`:due: 2026-08-15 09:00`) → a timed event sized by
    the task's `:estimate:` when set (e.g. `:estimate: 4h` → a 4-hour block),
    otherwise `event_duration_minutes` (default 30).
  - A **date-only** due (`:due: 2026-08-15`) → an **all-day** event by default
    (`all_day_for_dateless = true`; an all-day event has no duration, so
    `:estimate:` is ignored here), or a timed event starting at
    `workday_start` when `all_day_for_dateless = false` (also sized by
    `:estimate:` when set, otherwise `event_duration_minutes`).
- **`event_mode = "todo"`** — the task becomes a **VTODO** (a to-do item with a
  due date) instead of a visible timed event.

**Workday / break projection.** So a due doesn't land at an awkward hour, timed
events are kept inside your working day and out of your break:

- An event starting **before** `workday_start` is moved to `workday_start`.
- An event whose time slot **overlaps** the break window
  (`break_start`–`break_end`) is pushed to `break_end`. The whole event
  interval is checked, so a task due 11:45 for 30 min (ending 12:15) is moved to
  start at 13:00, not left straddling lunch.
- Events are never truncated, so a late due may still end after `workday_end`.

For example, with the default `08:00–17:00` workday and a `12:00–13:00` break, a
task due `11:45` with the default 30-minute duration is scheduled at
`13:00–13:30`.

**Timezones.** doto stores due dates/times as naive, *local* wall-clock values
and stamps a timezone only at the provider boundary. For timed events it uses
your machine's IANA timezone, resolved from `TZ` (then the `/etc/localtime`
symlink), falling back to `UTC`. doto never sends a bare abbreviation such as
`CEST` — Google and Microsoft reject those with *"Invalid time zone
definition"* — so on a minimal host without zone data, set `TZ` to a valid IANA
name (e.g. `TZ=Europe/Berlin`). All-day events are unaffected.

### Configuration (`[calendar]` in `.doto.toml`)

```toml
[calendar]
enabled = true
provider = "google"          # google | microsoft | apple | caldav
calendar = "primary"          # calendar id (Google/MS) or name/URL (CalDAV); blank = default
event_mode = "event"          # event (VEVENT) | todo (VTODO)
direction = "push"            # push (doto -> calendar) | two-way (calendar <-> doto)
conflict_policy = "local-wins"  # local-wins (default) | merge (git-style 3-way, two-way only)

# Event projection (event_mode = "event")
event_duration_minutes = 30
workday_start = "08:00"
workday_end = "17:00"
break_start = "12:00"
break_end = "13:00"
all_day_for_dateless = true   # date-only dues -> all-day events

# Auth (CalDAV / Apple): never commit a real secret -- use a $VAR reference
url = "https://caldav.icloud.com/"   # CalDAV base URL (Apple default shown)
username = "you@icloud.com"
password = "$DOTO_CAL_PASSWORD"       # $VAR / ${VAR} resolved from the environment

# Auth (Google / Microsoft): path to a downloaded OAuth client-secrets JSON
oauth_client_secrets = "~/.config/doto/google_client_secret.json"
```

The `password` field supports `$VAR` / `${VAR}` environment-variable references
(resolved at use time) so you can keep the secret out of the committed config.

### CLI commands

| Command | Description |
|---------|-------------|
| `doto calsync status` | Show the current config and a dry-run plan (how many items would be created/updated/deleted). |
| `doto calsync login` | Run the provider's OAuth2 browser flow (Google/Microsoft). For CalDAV/Apple it just verifies the username/password. |
| `doto calsync logout` | Clear the cached OAuth token for the provider. |
| `doto calsync push` | Push tasks to the calendar. `--dry-run`/`-n` previews without changing anything; `--exclude-done` keeps completed tasks off the calendar (and removes previously-synced ones). |
| `doto calsync pull` | Import/reconcile calendar events into doto (calendar → doto). `--dry-run`/`-n` previews. New user-created events become tasks; a remote event you delete archives its task. |
| `doto calsync sync` | Push-only by default; runs a full **two-way** sync (pull then push) when `direction = "two-way"`. `--dry-run` previews both directions. |

A typical first run:

```bash
# Google / Microsoft: authenticate once (opens a browser)
doto calsync login

# Preview, then push
doto calsync push --dry-run
doto calsync push
```

Sync is **incremental and idempotent**: doto records what it pushed (remote id,
ETag, and a content hash) in `.doto/calsync.json`, keyed by `provider::calendar`.
A second `push` with no task changes does nothing; changing a task updates its
item; archiving a task, removing its due date, or deleting it removes the item.

### Two-way sync (calendar → doto)

With `direction = "two-way"`, `doto calsync sync` runs a **pull** pass
(calendar → doto) and then the usual **push** pass (doto → calendar). You can
also run the inbound pass on its own with `doto calsync pull`.

What pull does:

- **New user-created events** (events you or another tool created directly in
  the calendar — i.e. *not* carrying a `doto-<id>@doxtr-doto` UID) are
  **imported** as new doto tasks: the event summary becomes the task title,
  its description becomes the task body (doto's own `[doto:…]` back-reference
  marker, if present, is stripped — including when a provider stores the
  description as HTML and separates or glues the marker with `<br>` tags, as
  the Google web UI does), and its start/date becomes the task `:due:`
  (date-only for all-day events, otherwise keeping the time). For a **timed**
  event, its duration (end − start) becomes the task `:estimate:` when it
  differs from the calendar's default `event_duration_minutes`, so a slot you
  sized on the calendar (e.g. 10:45–11:30 → `45m`) sets the task's expected
  duration. The task is created with status `open`.
- **doto-owned events** (ones push created) are left alone by pull — they
  round-trip through push.
- **Changed** imported events update the corresponding task's title, body, and
  due on the next pull.
- **Deleted** events: if an event doto previously imported is gone from the
  calendar, doto treats it as a user deletion and **archives** the
  corresponding task (a soft delete — the task is never hard-deleted, so it is
  recoverable).

Imported remote items are tracked in `.doto/calsync.json` by their calendar
UID, so pull is **idempotent**: re-running with no remote changes does nothing.

**Ordering.** Pull runs **before** push so that freshly imported events exist
as tasks before push plans its work (otherwise push could mistake a brand-new
import for a task that was deleted locally).

**Conflict policy.** When both a task *and* its doto-owned calendar event
changed since the last sync, how the two edits are reconciled is controlled by
`conflict_policy` in the `[calendar]` table (only consulted for `direction =
"two-way"`):

- **`conflict_policy = "local-wins"` (default).** doto is the system of record
  for the items it owns: the remote edit is discarded and push overwrites the
  calendar item with the local state, so local work is never lost. A
  remote-only edit of a doto event (the local task unchanged) is likewise
  discarded on the next push. Conflicts are reported so you can reconcile a
  discarded remote edit by hand.
- **`conflict_policy = "merge"`.** doto performs a **git-style three-way merge**
  of the two edits against the last-synced state:
  - A field changed on only one side takes that side (so a note you type into
    the calendar app flows back into the task body, a local edit still reaches
    the calendar, and resizing the event's end time updates the task
    `:estimate:`).
  - The multi-line **body** is merged **line by line**, so non-overlapping edits
    on both sides are combined.
  - A region that genuinely diverged on both sides is written with git-style
    `<<<<<<<` / `=======` / `>>>>>>>` conflict markers for you to resolve (the
    scalar `title` / `due` / `estimate` keep the local value and are flagged).
    The merged result is written locally **and re-pushed**, so both sides
    converge.
  - Merged tasks (and any that need manual conflict resolution) are listed in
    the sync output.

  The three-way merge needs the last-synced values as a common ancestor; those
  are recorded on every push, so merging is fully accurate from the first sync
  after a task has been pushed once.

### Per-provider setup

**Apple iCloud / generic CalDAV** — no app registration needed. For iCloud,
generate an **app-specific password** at [appleid.apple.com](https://appleid.apple.com)
and use it as `password`; the default `url` is `https://caldav.icloud.com/`.
For other CalDAV servers, set `url` to the server's CalDAV base URL and
`calendar` to the collection name or URL.

**Google / Microsoft** — these use OAuth2. A single OAuth *client* identifies
"the doto application"; **each user signs in once** via the browser and doto
caches a per-user, auto-refreshed token under the config dir (`0600`
permissions). Ordinary users do **not** create a cloud project — they only need
a client to be available:

- Point `oauth_client_secrets` at a client-secrets JSON you downloaded from
  [Google Cloud Console](https://console.cloud.google.com/) (OAuth client of
  type *Desktop app*, Calendar API enabled) or from an Entra ID app
  registration for Microsoft.
- Until the app is formally verified by the provider, the consent screen may
  show an "unverified app" warning and require the account to be added as a
  *test user*.

### Extending with a custom provider

Providers are resolved through an open registry, so a child project can add or
replace a provider **without editing core** (same pattern as the directive
renderer and restore-strategy registries):

```python
from doxtr_doto.calsync.providers import register_provider
from doxtr_doto.calsync.providers.base import CalendarProvider

class MyProvider(CalendarProvider):
    name = "myprovider"
    def connect(self): ...
    def create_event(self, event): ...
    def update_event(self, event, *, etag="", href=""): ...
    def delete_event(self, uid, *, etag="", href=""): ...

# Wrap the import in a loader so the provider's deps stay lazy.
register_provider("myprovider", lambda: MyProvider)
```

Similarly, the task → calendar-item mapping can be swapped with
`doxtr_doto.calsync.model.register_projector(fn)` to customize durations,
categories, or VTODO handling independently of any provider.

## Bidirectional Sync

The `.doto/tasks.json` file is the source of truth. The CLI operates on JSON, while Sphinx builds perform bidirectional sync:

- Changes in RST files are detected via content hashing
- Changes in JSON (via CLI) are merged back to RST
- 3-way merge detects and reports conflicts
- Archived tasks are removed from RST but preserved in JSON. When a task is archived, a **restore anchor** (the surrounding context and the original page title) is captured into the task's JSON `_sync._archive` block so the directive can be put back in the same place when the task is reopened.
- Removing a task's `.. doto::` directive by hand-editing the RST is treated as a deletion: a task that previously had its directive in that file (tracked by its `_sync.rst_hash`) is marked `done` and archived (not re-inserted), so it drops off active lists and appears on the archive page. (Tasks created only via the CLI, which were never in RST, are still created in RST on the next build.)
- New tasks defined only in RST (including bare `.. doto::` directives with an auto-generated `{docname}-L{lineno}` ID) are created in `tasks.json` on the next build, so they appear in `doto list` and other CLI commands
- When a bare `.. doto::` directive uses an auto-generated `{docname}-L{lineno}` ID, that generated `:id:` is written back into the RST file on the next build. This makes the ID stable: subsequent builds reuse the explicit `:id:` even if the directive's line number shifts, preventing the task from being orphaned and recreated as a duplicate

### Overriding directive rendering

All `.. doto::` directive text that doto writes into your RST files is produced
through a single overridable seam in `doxtr_doto.sync.rst_writer`, mirroring the
xlink resolver seam and the restore-strategy registry. A downstream project or
child theme can replace **all** directive-text rendering with its own
implementation without editing core:

```python
from doxtr_doto.sync import rst_writer


def my_renderer(task_data: dict) -> str:
    # task_data includes the task fields (must contain "id").
    # Return the full `.. doto::` directive text.
    ...


rst_writer.register_directive_renderer(my_renderer)
```

- `register_directive_renderer(fn)` installs a `(task_data) -> rst text`
  renderer used by every internal directive insertion/restore.
- `render_directive_text(task_data)` is the single dispatch point core routes
  through (it calls the active renderer).
- `reset_directive_renderer()` restores the built-in default,
  `generate_directive_text`.

## Archiving and the Archive Page

Auto-archiving is **enabled by default** (`doto_auto_archive = True`). When a
task reaches an archive status (`doto_archive_statuses`, default `["done"]`),
optionally after `doto_archive_after_days` days:

1. Its `.. doto::` directive is removed from the source RST file.
2. The task is preserved in `.doto/tasks.json` with `archived: true`.
3. It is listed on the archive page (`doto_archive_doc`, default
   `_doto_archive`).

Set `doto_auto_archive = False` to keep completed tasks inline in the RST
instead.

### The archive page and the `doto-archive` directive

The archive page is rendered by a dedicated `.. doto-archive::` directive,
which reads archived tasks directly from the JSON task store (via the build
environment) and renders their id, title, status, priority, assignee,
`archived_on` date, original page, and body. The virtual archive page emits
this directive automatically, but you can also place it on any page:

```rst
Archive
=======

.. doto-archive::
```

Rendering goes through the same node + template/theme system as `doto-list`, so
a child theme can replace it by shipping its own
`_doto/templates/html/doto-archive.html` (see [Custom Theme Override](#custom-theme-override)).

### Reopening: restore-to-place

Reopening a task (`doto reopen <id>`, or setting it back to an active status)
re-inserts its directive into the **original** RST file using the captured
restore anchor:

- **Same place** - If the anchor's surrounding context is still present and
  unambiguous, the directive is re-inserted at that exact location.
- **Heavily-modified fallback** - If the anchor no longer matches (the
  preceding context changed, is missing, or now appears more than once), the
  directive is inserted at the **top of the page**, directly under the first
  heading, so it is never lost. "Heavily modified" is defined precisely as: the
  recorded run of preceding non-blank source lines does not appear exactly
  once in the current file.
- **Renamed/deleted page** - If the original RST file no longer exists, the
  task is **not** silently relocated to the inbox. Instead the reopen fails for
  that task with a message that names the page by its **title** and its
  **docname** (the Sphinx document name, e.g. `tasks/sprint-1`, not a full
  filesystem path and with no `.rst` extension):

  ```
  this doto was originally on a page with title "<title>" at "<docname>",
  which no longer exists; it was not relocated so you can retrace where it belongs
  ```

  so you can find where the task used to live. This behavior is reachable from
  both the CLI `doto reopen` command and the build-time reopen path.

## Theming

### Custom Theme Override

To customize doto's appearance, create a `_doto/` directory in your Sphinx source:

```
my-project/
├── _doto/
│   ├── html/
│   │   └── doto-custom.css
│   ├── latex/
│   │   └── doto-custom.sty
│   ├── epub/
│   │   └── doto-custom.css
│   └── templates/
│       └── html/
│           └── doto-archive.html
├── conf.py
└── index.rst
```

Files in `_doto/` take precedence over built-in themes. This allows project-specific styling without modifying configuration.

### HTML

Built-in themes: `default`, `minimal`

CSS variables for customization:

```css
:root {
  --doto-priority-low: #6c757d;
  --doto-priority-medium: #0d6efd;
  --doto-priority-high: #fd7e14;
  --doto-priority-critical: #dc3545;
}
```

### epub

Built-in themes: `default`, `minimal`

Set via `doto_epub_theme` in conf.py. epub styles are optimized for e-readers with `page-break-inside: avoid` and simplified layouts.

### LaTeX/PDF

Uses `tcolorbox` for styled output. Customize column widths with `doto_latex_column_specs`:

```python
doto_latex_column_specs = {
    "title": r"p{6cm}",  # Wider title column
    "priority": r"c",  # Centered
}
```

Custom styles via `doto_latex_preamble`.

#### PDF task-box layout (`doto_latex_layout`)

Task boxes support two layouts, selected globally via `doto_latex_layout` and
overridable per directive with `:latex-layout:`:

```python
# conf.py
doto_latex_layout = "default"  # "default" (roomy) | "compact" (dense)
```

- **`default`** (the original look, fully backward compatible): each task
  renders as a `dotobox<priority>` `tcolorbox` with a filled title bar and the
  metadata laid out as roomy **stacked** icon-over-label rows (one group per
  row: id/priority, status, assignee/due, created/updated, tags, raci).
- **`compact`**: the **same fields** laid out densely in a
  `dotoboxcompact<priority>` box with tighter geometry — a **single-line
  header** (title + id + priority + status) followed by the remaining fields as
  **inline icon+value pairs** (`\dotocompactfield{icon}{value}`) separated by a
  thin rule. No detail is dropped relative to `default`; only the geometry and
  icon placement are denser (icons are grouped inline rather than stacked
  per-row).

The per-directive override wins over the config and lets a single task opt into
the other layout:

```rst
.. doto:: Dense task
   :id: TASK-1
   :latex-layout: compact
```

An unrecognized layout value (config or directive) falls back to `default`, so
a typo can never emit an undefined box environment.

The task-list `:icon-mode:` (icon / icon-text / text) is independent of the box
layout and keeps working in both layouts.

**Overriding the layouts (child theme seam).** The `.sty` macros are the single
source of visual truth. `nodes.py` only *selects* an environment/macro name;
all geometry and icon placement live in `doto.sty`. A child theme ships its own
`doto.sty` (or a project `_doto/latex/*.sty`) and redefines any of:

- the box environments `dotobox<priority>` (default) and
  `dotoboxcompact<priority>` (compact), and
- the compact body macros `\dotocompactheader{title}{id}{priority}{status}`,
  `\dotocompactrule`, `\dotocompactfield{icon}{value}`, and `\dotocompactsep`
  (default-layout bodies use the existing `\dotometa*` macros).

### Doxtr Integration

When `doxtr-pdf-theme-core` is available (and `doto_doxtr_integration` is `auto`
or `enabled`), doto integrates with its color and layout systems automatically
for PDF/LaTeX output. Standalone builds (without the theme core) keep doto's
built-in defaults unchanged.

```python
# conf.py
doto_doxtr_integration = "auto"  # auto | enabled | disabled
```

**Semantic colors.** When the theme core is active, doto derives its
task-box, priority, and status colors from the core's merged semantic palette
(core defaults → active theme → your `doxtr_semantic_palette` overrides) via the
core's `dd:` expression system (e.g. `dd:danger` for `critical`, `dd:warning`
for `high`, `dd:info` for `in-progress`), emitting them as `\definecolor`
overrides into the LaTeX preamble after `\usepackage{doto}`. Brand keys such as
`primary`/`danger` come from the core defaults, so colors stay themed even if
you override only a few keys (or none). Only standalone builds — without the
theme core — keep the `doto.sty` defaults.

The light-palette source is isolated behind a single overridable seam,
`doxtr_doto.integration._core_light_palette_defaults(app)`. A child theme (or a
future public-core accessor) can redirect where doto's merged light palette
comes from by overriding just that one function; the three-tier merge
orchestration stays unchanged.

**Auto-landscape wide tables.** When integrated and the theme core's
`doxtr_table_auto_landscape` is enabled (the default), a `doto-list` task table
whose column count is at least `doxtr_landscape_min_columns` (theme-core option,
default `4`) is wrapped in the core's breakable landscape environment so it
rotates to landscape automatically and does not overflow the page margins.
Narrow tables (below the threshold) are left in portrait, and standalone builds
emit the unrotated table unchanged.

> `doxtr_semantic_palette`, `doxtr_table_auto_landscape`, and
> `doxtr_landscape_min_columns` are configuration values owned by
> `doxtr-pdf-theme-core`; doto only reads them when the theme core is active.

## Development

Set up a local development environment and run the checks that CI enforces:

```bash
pip install -e ".[dev]"
python scripts/check_imports.py     # circular-import check (also run in CI)
ruff format --check src tests        # formatting check (ruff is pinned in [dev])
ruff check src tests                 # lint check
python -m pytest                     # runs the suite with the coverage gate (fails under 80% via pyproject)
```

The `dev` extra pins `ruff==0.16.9` (an exact pin, unlike the other dev deps) so every contributor produces identical formatting; the whole tree is formatted with `ruff format` and must pass `ruff format --check` and `ruff check`. Run `ruff format src tests` to apply formatting before committing.

The coverage gate is set to 80% to guard against coverage drift (current coverage is ~83%). The threshold lives in a single place, `pyproject.toml` `[tool.pytest.ini_options]` `addopts`, so running `python -m pytest` locally enforces the same gate as CI. The same import-cycle check (`scripts/check_imports.py`) runs in CI before the test suite.

## License

MIT License
