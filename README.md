# doxtr-doto - Documentation Task Management for Sphinx

**doxtr-doto** (documentation task open) is a Sphinx extension for managing documentation tasks with structured metadata, bidirectional sync with JSON storage, and a companion CLI tool.

## Features

- **Structured task directives** - Define tasks with priorities, assignees, due dates, tags, and dependencies
- **Task lists and summaries** - Display filtered, sorted task lists and statistics
- **Styled PDF task boxes** - Each task renders as a `tcolorbox` with a high-contrast title bar and readable body (no more white-on-white boxes)
- **Stacked Font Awesome metadata icons** - PDF task boxes stack a semantic FA icon above each metadata label (calendar for due, user for assignee, flag for priority, etc.), degrading gracefully when Font Awesome is unavailable
- **Task-list icon modes** - Render list cells as Font Awesome icons, icon+text, or text, with clickable task IDs/titles
- **Cross-references** - Link to tasks with the `:doto:` role; PDF cross-references are clickable hyperlinks that jump to the task box
- **Bidirectional sync** - Keep RST files and JSON storage in sync with 3-way merge
- **Auto-archiving** - Automatically archive completed tasks
- **CLI tool** - Manage tasks from the command line
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
    'doxtr_doto',
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
| `:id:` | string | Auto-generated | Unique task identifier |
| `:assignee:` | string | None | Person responsible |
| `:priority:` | enum | `medium` | `low`, `medium`, `high`, `critical` |
| `:status:` | enum | `open` | `open`, `in-progress`, `blocked`, `done` |
| `:due:` | date | None | Due date (YYYY-MM-DD) |
| `:tags:` | list | None | Comma-separated categories |
| `:depends-on:` | list | None | Comma-separated task IDs |

### `.. doto-list::` - Task List

Displays a filtered list of tasks.

**Filter Options:** `:assignee:`, `:priority:`, `:status:`, `:tags:`, `:due-before:`, `:due-after:`, `:exclude-status:`

**Display Options:** `:sort:`, `:order:`, `:limit:`, `:format:` (table/list/cards), `:show-archived:`, `:columns:`, `:icon-mode:` (icon/icon-text/text)

Task IDs and titles in every list format are clickable links to the task box.
The `:icon-mode:` option overrides the global `doto_list_icon_mode` config for
a single directive.

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
doto_auto_archive = False
doto_archive_doc = "_doto_archive"
doto_archive_after_days = 0

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

# Charts
# Chart engine for doto-summary: "svg" (default) or "plotly".
#   "svg"    = built-in inline-SVG charts, no extra dependencies
#   "plotly" = renders static images via plotly + kaleido; falls back
#              automatically when plotly/kaleido/Chrome are unavailable
#              (inline SVG for HTML output, native TikZ charts for PDF/LaTeX)
# Requires the [charts] extra when set to "plotly".
doto_chart_engine = "svg"

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

# Customize default columns for 'doto list'
list_columns = ["id", "title", "status", "priority", "assignee"]

# Valid values
statuses = ["open", "in-progress", "blocked", "done"]
priorities = ["low", "medium", "high", "critical"]
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DOTO_JSON_FILE` | Path to tasks.json |
| `DOTO_DEFAULT_PRIORITY` | Default priority for new tasks |
| `DOTO_DEFAULT_STATUS` | Default status for new tasks |
| `DOTO_LIST_COLUMNS` | Comma-separated list of columns for `doto list` |
| `DOTO_COLOR` | Color mode: `auto`, `always`, `never` |

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

# Update a task
doto update TASK-001 --status in-progress

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

**Supported recurrence patterns:**

| Pattern | Example |
|---------|--------|
| Daily | `every day`, `every 3 days` |
| Weekly | `every friday`, `every 2 weeks on monday` |
| Monthly (day) | `every month on 15`, `every 2 months on 1` |
| Monthly (weekday) | `every month on first monday`, `every month on last friday` |
| Quarterly | `every 3 months on first monday` |

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

# Delete a series and all its tasks
doto series delete SER-001

# Delete series but keep the tasks
doto series delete SER-001 --keep-tasks
```

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

### CLI Commands Reference

| Command | Description |
|---------|-------------|
| `init` | Initialize doto in a project |
| `completion` | Set up shell tab completion (bash/zsh/fish) |
| `config` | Show current configuration (JSON path, mode, defaults) |
| `add` | Add a new task (supports `--repeat` for recurring tasks) |
| `list` | List tasks with filters and sorting |
| `show` | Show details of a specific task |
| `update` | Update task fields |
| `done` | Mark tasks as done |
| `next` | Show the next task to work on |
| `tree` | Display tasks as a dependency tree |
| `reopen` | Reopen archived tasks |
| `deps` | Show task dependencies (blocking tasks) |
| `series` | Manage recurring task series |
| `resolve` | Resolve merge conflicts between RST and JSON |
| `delete` | Permanently delete tasks (supports filters) |
| `archive` | Archive tasks (hide from listings, can reopen) |
| `export` | Export tasks to various formats (JSON, CSV, Markdown) |
| `search` | Search tasks by text pattern or regex |
| `stats` | Show task statistics |

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

## Bidirectional Sync

The `.doto/tasks.json` file is the source of truth. The CLI operates on JSON, while Sphinx builds perform bidirectional sync:

- Changes in RST files are detected via content hashing
- Changes in JSON (via CLI) are merged back to RST
- 3-way merge detects and reports conflicts
- Archived tasks are removed from RST but preserved in JSON

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
│   └── epub/
│       └── doto-custom.css
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
    "priority": r"c",    # Centered
}
```

Custom styles via `doto_latex_preamble`.

### Doxtr Integration

When `doxtr-pdf-theme-core` is available (and `doto_doxtr_integration` is `auto`
or `enabled`), doto integrates with its color and layout systems automatically
for PDF/LaTeX output. Standalone builds (without the theme core) keep doto's
built-in defaults unchanged.

```python
# conf.py
doto_doxtr_integration = "auto"  # auto | enabled | disabled
```

**Semantic colors.** If a `doxtr_semantic_palette` is configured on the theme
core, doto derives its task-box, priority, and status colors from that palette
(via the core's `dd:` expression system, e.g. `dd:danger` for `critical`,
`dd:warning` for `high`, `dd:info` for `in-progress`) and emits them as
`\definecolor` overrides into the LaTeX preamble after `\usepackage{doto}`. This
means task boxes match the surrounding theme instead of doto's hardcoded
defaults. Without a palette (or without the theme core), the defaults in
`doto.sty` are used.

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
python -m pytest                     # runs the suite with the coverage gate (fails under 80% via pyproject)
```

The coverage gate is set to 80% to guard against coverage drift (current coverage is ~83%). The threshold lives in a single place, `pyproject.toml` `[tool.pytest.ini_options]` `addopts`, so running `python -m pytest` locally enforces the same gate as CI. The same import-cycle check (`scripts/check_imports.py`) runs in CI before the test suite.

## License

MIT License
