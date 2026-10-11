# Changelog

All notable changes to doxtr-doto will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

## [0.2.0] - 2026-10-11

### Added

#### Multi-repo views: short task IDs when unambiguous
- In aggregated/global views (`doto list -r`, `doto tui` Global scope), a task
  ID is now shown **bare** (e.g. `CALC-002`) instead of `repo#id` when its base
  prefix — the identifier with a trailing `-<digits>` stripped (`CALC` for
  `CALC-002`) — is used by only one repo in the current (already-gathered)
  view. When two or more repos share a base prefix in that view, every task in
  that group keeps the full `repo#id` form so it stays unambiguous.
  Shortening is **display-only**: `_repo`/`_local_id` are preserved and all
  mutating actions/resolution still use the canonical ref, so a shortened
  foreign-repo task resolves to its owning repo. Seam:
  `cli/display.py::apply_scope`, helper `cli/id_resolver.py::base_id`.

#### TUI card viewer: RACI (differing from default user) + Time spent
- The TUI card viewer popup (`Enter` on a task in the list / kanban / calendar
  layouts) now shows two extra **TUI-only** fields below the shared
  `doto list -f cards` fields:
  - **RACI differing from your default user.** RACI roles/names are shown, but
    a role assigned *only* to your configured default user (`config.user`,
    falling back to `config.default_assignee`) is suppressed as the boring
    default; only the entries that differ are rendered, grouped by role with
    their R/A/C/I labels. The default-user comparison is case-insensitive,
    matching the project's name-dedup policy. New pure helpers
    `doxtr_doto.raci.filter_raci_differing(raci, default_user)` and
    `doxtr_doto.raci.render_raci_differing_lines(raci, default_user)`, with the
    overridable `register_raci_differing_renderer` /
    `reset_raci_differing_renderer` seam.
  - **Time spent.** How long work has been clocked on the task, summed from its
    worklogs (`doxtr_doto.time_tracking.elapsed_seconds`) and formatted like
    `1h02m03s` (`doxtr_doto.cli.session.format_duration`). An active (running)
    session counts up to "now"; the line is omitted when no time has been
    tracked. New pure helper
    `doxtr_doto.cli.session.render_time_spent_line(worklogs, now=None)`, with
    the overridable `register_time_spent_renderer` / `reset_time_spent_renderer`
    seam.
- The two fields are assembled by the overridable instance method
  `CardViewerScreen.build_extra_field_lines`, which is threaded with the
  resolved default user (`DotoApp._default_user`) via the viewer's new
  `default_user` constructor argument. The shared, single-source CLI card
  builder `doxtr_doto.cli.output.build_task_detail_lines` is unchanged, so the
  CLI `doto list -f cards` output is unaffected.

#### TUI: literal + accent-highlighted bracketed titles
- In the interactive TUI (`doto tui`), free-text task titles that contain a
  `[...]` run (e.g. `[WIP] fix the thing`) now render the brackets **literally**
  instead of being misparsed as Textual style markup. Previously a title like
  `[red] oops` dropped the bracketed text and `[/]` could raise a markup error;
  titles are now backslash-escaped so they render as typed and keep their true
  display width on every surface (table / list / kanban / calendar / details /
  card viewer / kickstart nudge).
- Each bracketed run is additionally drawn in the **active theme's accent**
  colour - the same hue the Textual footer uses for key labels like `tab`. The
  accent is resolved from the live theme to a concrete hex at render time
  (console/Rich markup cannot reference the `$accent` CSS token directly), so
  the highlight tracks theme changes from the command palette and stays
  width-stable in the framed kanban board. The seam is child-theme overridable
  via `TitleHighlight.BRACKET_HIGHLIGHT_STYLE` / `TitleHighlight.escape_title`
  and the app's `resolve_bracket_accent` hook.

#### TUI: accent-coloured selected kanban card frame
- The currently selected card in the kanban pane is now outlined with a frame
  drawn in the **active theme's accent** colour (resolved to a concrete hex at
  render time), replacing the previous reverse-video frame. With no accent
  resolved it falls back to the prior `bold reverse` highlight, so the frame
  stays visible on every built-in theme. The colour is child-theme overridable
  via `KanbanView.SELECTED_FRAME_ACCENT` / `KanbanView.frame_style` and the
  app's `resolve_frame_accent` hook; both accent highlights share a single
  `resolve_accent` default so they match by default while remaining
  independently retargetable.

#### Calendar sync (push-first) - `doto calsync`
- New provider-agnostic calendar-sync subsystem that pushes tasks with a due
  date to an external calendar, behind the optional `calendar` extra
  (`pip install 'doxtr-doto[calendar]'`). All provider SDKs are imported
  lazily, so core doto keeps working without the extra installed.
- Providers: **Google** and **Microsoft** (REST + OAuth2) and **Apple
  iCloud / generic CalDAV** (username + app-specific password), behind an open
  `register_provider()` registry so a third party can add a provider without
  forking.
- Direction is **push-only** today (doto -> calendar); the engine is
  direction-aware so two-way can be added later, and a `direction = "two-way"`
  config value is rejected with a clear message.
- Tasks are projected to a calendar item via a swappable `register_projector()`
  seam: a `VEVENT` on the due date (`event_mode = "event"`) or a `VTODO`
  (`event_mode = "todo"`), with a configurable workday/break window (events
  overlapping the break are shifted to break-end; before-workday starts are
  clamped) and optional all-day projection for date-only dues.
- Sync is incremental and idempotent: per-task remote uid / etag / content hash
  are stored in `.doto/calsync.json`, namespaced by `provider::calendar`, so a
  re-push updates the same items instead of duplicating them, and doto only
  ever touches items it created (`doto-<id>` UID).
- CLI: `doto calsync status | login | logout | push | sync`, with `--dry-run`
  / `-n` and `--exclude-done`; configured via a `[calendar]` table in
  `.doto.toml` with on-demand validation.

#### Due dates with an optional time
- The `:due:` option (and the CLI `--due`) now accepts an optional **naive,
  local clock time** appended to the `YYYY-MM-DD` date, separated by a space or
  an ISO-style `T`. Accepted time syntaxes: `HH:MM` (`16:00`), the hour
  shorthand `HHh` (`16h` → `16:00`), and `HH:MM:SS` (`16:00:31`).
- A due with **no** time is fully backward compatible: it stays a plain date
  and renders, sorts, and serializes exactly as before.
- Storage is a single string that is either `YYYY-MM-DD` or
  `YYYY-MM-DDTHH:MM[:SS]`, round-tripped losslessly through RST and JSON
  (seconds dropped when zero). Old date-only JSON still loads unchanged; the
  JSON schema version is unchanged (no migration needed). Note that within the
  existing schema version the `due` string's grammar is now wider — a reader
  must tolerate the optional `T`-time (all in-repo readers do). An external
  tool that assumed a plain `date.fromisoformat(due)` on a date-only value
  should parse the full ISO datetime form instead.
- Rendering (HTML task box, LaTeX/PDF, list cells) shows the time as
  `YYYY-MM-DD HH:MM`; date-only rendering is unchanged. Formatting stays
  centralized in `date_utils` so a child theme's rendering override still
  receives a sensibly-formatted value.
- Overdue semantics: a date-only due is overdue once the day has fully passed
  (a task due *today* is not overdue — unchanged); a time-bearing due is
  overdue once that specific local instant has passed.
- Parsing/formatting is centralized in `doxtr_doto.date_utils.DotoDate` (now
  carrying an optional naive `time`); all CLI due parsing (`add`, `update`,
  `next`) routes through it so there is one place to change. This is the
  foundation a later calendar-sync feature will build on.

#### TUI repository filter + Global default scope
- The TUI now **defaults to Global scope** (`DotoApp` starts in
  `DisplayScope.GLOBAL`; `g` still toggles Global / Local).
- A new **repository filter** restricts which repositories' dotos are shown.
  It can be set both in the **filter & sort pop-up** (`F`) via a
  `Repositories` multi-select *and* in the **repo tree** (the table view's
  left pane) by selecting repository leaves, which toggles the same filter and
  marks the selected repos with a leading check.
- Filtering semantics: **Local** shows only the current repository's dotos
  (the repo filter is scope-gated off in Local, so a selection made in Global
  is ignored while Local - never emptying the Local list); **Global** with
  **no** repositories selected shows all repositories' dotos; **Global** with
  **one or more** selected shows only the selected repositories' dotos.
  Matching is on repo name.
- Implemented as the pure, overridable `filter_by_repos` helper plus a new
  `ViewPrefs.repo_filter` field in `doxtr_doto.cli.tui.filtersort`, wired into
  the existing `apply_filters` pipeline (so it stays a no-op until a repo is
  selected). The repo multi-select widget is overridable via
  `ViewPrefsScreen.repo_select_class`, and the tree's selection glyph via
  `RepoTree.format_marker`.
- The repository filter is **remembered** across sessions: it is persisted to
  `~/.config/doto/config.json` as the new `tui_repo_filter` field (a list of
  repository names) and restored on the next launch. Older config files that
  predate the field fall back to no repo filter (backward compatible).

#### TUI reverse layout cycle (`V`)
- `V` (Shift+V) now cycles the task-list layout in **reverse** (table ← list
  ← kanban ← calendar ← time), the exact mirror of the existing `v` forward
  cycle. Both share a single `_cycle_layout(step)` helper on `DotoApp`, persist
  the chosen layout via `save_tui_layout`, and are documented in the in-app
  help.

#### `doto timesheet` - daily worked-tasks CSV export
- New `doto timesheet` command exports a CSV of every worked interval on a
  given day - the global **work clock** intervals **and** each task's
  focus-session intervals (aggregated across every registered repository) -
  one interval per row. Start/end times are rounded to the **nearest
  quarter hour** via a midpoint rule (`< 7.5m` rounds down, `>= 7.5m` rounds
  up: `:07` → `:00`, `:08` → `:15`, `:43` → `:45`), implemented as a pure,
  child-overridable helper `work_report.round_to_quarter_hour`.
- A final `total` row reports the **exact, unrounded** work-clock span for the
  day (earliest work-clock start → latest work-clock stop, including mid-day
  gaps) as `HH:MM` - the work-clock span, not the sum of task times.
- Options: `--date`/`-d` (default today), `--output`/`-o` (default stdout),
  and `--columns` (comma-separated, validated) to choose/reorder columns.
  Available columns: `date`, `start_time`, `end_time`, `task_id`, `title`,
  `kind` (`work`/`task`/`total`) and `duration` (per-row rounded length).
- The CSV logic lives in pure functions in `doxtr_doto.work_report`
  (`timesheet_rows`, `work_span_seconds`, `timesheet_matrix`, `timesheet_csv`),
  kept separate from the click command so it is testable and a child theme can
  subclass/replace it.
- Free-text cells (`title`, `task_id`) that begin with a spreadsheet formula
  trigger (`=`, `+`, `-`, `@`, or a leading tab/carriage return) are prefixed
  with an apostrophe so they render as literal text and cannot auto-execute as
  a formula when the CSV is opened in Excel/Sheets/LibreOffice (CSV
  formula-injection hardening).

#### TUI active-task pin + filter/sort pop-up with sort memory
- **Active (time-recorded) task always on top:** the currently active task
  (the one with an open worklog session, started with `s`) is now pinned to
  the **top** of its list in *every* TUI layout - the top row of the table
  and list, the top card of its status column in the kanban board, and the
  top of its day's list (and the undated bucket) in the calendar. The pin is
  **stable** (non-running tasks keep their relative order; multiple running
  tasks keep theirs) and is applied **after** any sort, so the active task
  stays on top regardless of the chosen sort. Implemented as a pure,
  overridable `pin_active_first` helper that each view applies where it builds
  its rows.
- **Filter & sort pop-up (`F`):** a new modal pop-up (over the existing
  `/` free-text filter) configures the task list's filters and sort. Filters:
  hide completed (`done`) tasks, show only tasks due **today**, due **this
  week** (today through the coming Sunday), only a chosen **tag**, and only a
  chosen **priority**. Sort by due date / priority / tag / **`next`** (the
  recommended-next ordering, reusing the exact `doto next` scoring rather than
  duplicating it) with an ascending / descending order.
- **Sort memory:** the last filter **and** sort state is remembered across
  sessions - persisted to `~/.config/doto/config.json` (new
  `tui_hide_completed`, `tui_due_filter`, `tui_tag_filter`,
  `tui_priority_filter`, `tui_sort_key`, `tui_sort_order` fields) and restored
  on the next launch. Older config files that predate these fields fall back
  to no filter / no sort (backward compatible, preserved via the forward-compat
  `_extra` round-trip).
- **Composition order** in `DotoApp._visible_tasks`: gather → free-text
  filter → `F` pop-up filters → sort → pin active task to top, each step a
  separate overridable call.
- **Overridable seams:** the pop-up is its own `DotoApp.view_prefs_screen_class`
  (mirroring the other `*_screen_class` modals), and the pure filter/sort
  helpers live in the new `doxtr_doto.cli.tui.filtersort` module
  (`ViewPrefs`, `apply_filters`, `apply_sort`, `pin_active_first`,
  `apply_view_prefs`) with new `DueFilter` / `SortKey` / `SortOrder` enums, so
  a child theme can swap either.

#### Compact PDF/LaTeX task-box layout (`doto_latex_layout`)
- **New `doto_latex_layout` config option** (`"default"` | `"compact"`, default
  `"default"`, fully backward compatible) selects the PDF/LaTeX task-box
  layout. `"default"` keeps the original roomy `dotobox<priority>` box with
  stacked icon-over-label metadata rows (byte-identical output). `"compact"`
  renders the **same fields** (id, priority, status, assignee, due, created,
  updated, tags, raci) much more densely in a new `dotoboxcompact<priority>`
  box: a single-line header (title + id + priority + status) plus inline
  icon+value field pairs separated by a thin rule, with tighter box geometry.
  No detail is dropped relative to the default layout.
- **Different icon layout in compact mode:** icons are grouped inline
  (`\dotocompactfield{icon}{value}`) rather than stacked per metadata row. The
  existing task-list `:icon-mode:` (icon / icon-text / text) is independent of
  the box layout and keeps working in both.
- **Per-directive override:** `.. doto::` gains a `:latex-layout:` option
  (`default` / `compact`) that wins over the config for a single task. An
  unrecognized value (config or directive) falls back to `default`, so a typo
  can never emit an undefined box environment; invalid `doto_latex_layout`
  values also surface a validation warning.
- **Child-theme override seam:** all geometry/icon placement lives in the
  `.sty` macros (`doto.sty` / `doto-minimal.sty`); `nodes.py` only selects an
  environment/macro name. A child theme redefines the box environments
  (`dotobox<priority>`, `dotoboxcompact<priority>`) and the compact body macros
  (`\dotocompactheader`, `\dotocompactrule`, `\dotocompactfield`,
  `\dotocompactsep`) in its own `.sty` to restyle either layout without
  touching Python.

#### Per-doto time reporting + session editing in the TUI `time` layout
- **Per-doto time reporting:** the TUI `time` layout gains a per-doto
  time-reporting pop-up, opened with **`T`** (a no-op outside the `time`
  layout). For a chosen granularity (`d` / `w` / `m` / `y`, `g` to cycle, with
  `←` / `→` navigating the period across years) it shows **how long you
  worked on which dotos** - each doto's total focus-session time (sorted
  descending, as a text `█` bar chart) plus the per-repository totals,
  aggregated across every registered repository. The aggregation reuses the
  existing `work_report.compute_task_breakdown` math and a new shared
  cross-repo task collector (`doxtr_doto.cli.task_collector.collect_repo_tasks`)
  that `doto report` now uses too (the collector was factored out of the
  `report` command, with no behavior change for the CLI).
- **Per-doto session editing:** pressing **`E`** on the highlighted doto (in
  the table / list / kanban / calendar layouts) opens a per-doto session editor
  that lists that single doto's recorded focus sessions (start → stop with
  per-interval and total duration) and supports **add** (`a`), **edit**
  (`e` / `Enter`), and **delete** (`x`), persisting each change back to that
  doto's owning repository store. It reuses the shared `apply_interval_edit` /
  `remove_interval` primitives and the same **Edit work interval** pop-up as
  the global work-time manager.
- **Overridable seams:** both surfaces are exposed as overridable `DotoApp`
  class attributes (`task_time_stats_screen_class` / `task_sessions_screen_class`,
  mirroring `work_stats_screen_class` / `work_time_screen_class`) and render
  through pure `format_*` classmethods, so a child theme can replace the
  rendering without rewriting the app. All aggregation / mutation / formatting
  logic lives in importable pure helpers (`task_breakdown_chart_rows`,
  `task_repo_chart_rows`, `task_interval_display_rows`) that are unit-testable
  without rendering Textual.

#### RACI role information on tasks
- **Tasks can now carry RACI role metadata** (Responsible, Accountable,
  Consulted, Informed). RACI is stored as a mapping of each role to a list of
  people, e.g. `{"responsible": ["alice"], "accountable": ["alice"],
  "consulted": ["charlie"], "informed": ["diana"]}`.
- **RST directive:** a new `:raci:` option accepts comma-separated `role name`
  pairs (`:raci: responsible alice, accountable bob, consulted carol, informed
  dave`), with single-letter abbreviations (`r`, `a`, `c`, `i`) and multiple
  people per role.
- **CLI:** `doto add --raci "..."` and `doto update --raci "..."` (update
  merges with existing roles). When adding a task, Responsible and Accountable
  default to the configured user so RACI never gets in the way of a quick add.
- **Configured user with environment-variable resolution:** the current user is
  resolved from the `DOTO_USER` environment variable, then `[doto] user` in
  `.doto.toml`, then `doto_default_user` in `conf.py`, then a `$USER` fallback.
  Values may embed `$VAR` / `${VAR}` references, which are expanded from the
  environment.
- **Rendering:** RACI renders in the single-task box (HTML and LaTeX) and as a
  compact `R: alice, A: bob` summary in list columns. Both the box HTML
  renderer and the compact renderer are overridable seams
  (`register_raci_html_renderer` / `register_raci_compact_renderer`) so a child
  theme can replace RACI rendering without editing core code. The TUI edit
  screen gains four RACI inputs (overridable via `RACI_FIELDS` /
  `build_raci_inputs` / `raci_suggester`).

#### Remembered assignees and tags
- **doto now remembers assignee names and tags you have used** so they are
  suggested the next time, even if no current task references them. Known names
  are stored in `.doto/known_names.json` (atomic writes, case-insensitive
  dedup). Shell completion and the TUI edit-screen suggesters merge these
  remembered names with names drawn from existing tasks. Persistence is
  best-effort and never blocks an add/update.

### Changed

#### Full strict-mypy type coverage + CI type gate
- **The entire `src` tree now passes `mypy --strict` with zero errors** (down
  from 324). Fixes are real type annotations (generic arguments, parameter and
  return types, `Mapping` widenings, `WorkLog` TypedDict usage, `ClassVar`
  domain attributes); only a small number of narrowly-scoped
  `# type: ignore[code]` remain where third-party stubs are unavailable
  (docutils) or Sphinx stores dynamic attributes on the build environment.
- **CI now enforces the type gate:** `.github/workflows/test.yml` runs `mypy
  src` so the clean state cannot silently regress.

### Fixed

#### Calendar sync could emit an invalid timezone (abbreviation) for timed events
- Fixed a bug where pushing a task with a *timed* due date to Google (or
  Microsoft) could fail with `Invalid time zone definition for start time`.
  The provider stamps timed events with the local timezone, but
  `local_tz_name()` could return a timezone *abbreviation* such as `CEST`
  (e.g. when `TZ` is set but `/etc/localtime` resolves to a fixed-offset zone),
  which the Calendar APIs reject - they require a valid IANA name like
  `Europe/Berlin`. `local_tz_name()` now resolves and validates a true IANA
  zone in order (`TZ` env -> `/etc/localtime` symlink target -> `ZoneInfo.key`
  -> `str(tzinfo)`), never emitting a bare abbreviation, and falls back to
  `UTC` when no valid zone can be determined. All-day events were unaffected.

#### Focus timer could not be stopped after re-starting an auto-stopped task
- Fixed a bug where, in the TUI, starting a focus timer on task A, then on
  task B (which auto-stops A), then re-starting A, left A's focus timer
  impossible to stop - the green focus arrow stayed on. The root cause was
  that `JsonTaskStore.load()` reassigned its in-memory data but kept the
  cached task repository bound to the *previous* data, so reloading a store
  silently desynced reads/writes from what `save()` persisted. Because the
  TUI reuses one context across key presses while `doto start` opens the
  worklog through a freshly resolved store instance, the stale cache clobbered
  the on-disk worklog list - dropping worklogs and leaving a dangling open
  session. `load()` now rebinds the cached repositories to the freshly loaded
  data, and the shared `start_focus` / `stop_focus` / `_close_focus` helpers
  reload from disk before their read-modify-write and defensively enforce the
  single-open-session invariant (a task can never accumulate two open
  worklogs). The TUI's `toggle_timer` also reloads before deciding whether to
  start or stop, so the start-vs-stop choice is made against on-disk truth
  rather than a stale cache. The fix is at the shared command layer so the CLI
  and TUI never diverge.

#### TUI add-task into another repo uses that repo's id prefix
- **Adding a task into a non-current repository from the TUI now generates the
  id from the *target* repository's own `.doto.toml`, not the directory doto
  was launched in.** Previously the repo selector routed the new task into the
  chosen repository's store, but the id was still generated with the launch
  directory's config — so a task added into a repo whose `.doto.toml` set
  `id_prefix = "JENS"` was written into that repo's `tasks.json` yet received
  the launching directory's prefix (e.g. `DOTO-003` instead of `JENS-004`).
- **Fix:** when a repository is given, its own `.doto.toml` is loaded (via
  `load_config(config_path=...)`) and the id prefix / sequencing and task
  defaults come from that repository. The default no-repo path (current
  directory's store and config) is unchanged.

#### Breaks are the real recorded clock-out gaps (no more double-counted breaks)
- **A break is now the real clock-out gap you record, not an assumed
  time-based deduction.** Previously a configured recurring break only
  credited a clock-out gap against the break when that gap *started inside* the
  break's nominal time window `[time − leeway, time + leeway]`. A break taken
  **outside** that window (e.g. `12:55–13:34` for a `12:00` lunch) left the
  full configured duration deducted on top of the already-missing worked time,
  so the "Work time" view and `doto report` **double-counted** the break.
- **New rule:** net work for a day is the gross worked seconds (the sum of the
  work-clock intervals). Because any clock-out gap during the day already
  falls outside every clocked interval, it is already excluded from gross and
  needs no further deduction. Each recorded gap is **surfaced** as an explicit
  break (span + duration) in `doto report` (a new `Breaks taken:` section and
  `recorded_break_seconds` in the JSON) and in the TUI `time` view / summary
  panel / statistics pop-up — regardless of the time of day it happened. The
  JSON report also retains the `break_seconds` key (per period and per day),
  which stays `0` unless a break opts into auto-deduction.
- **Opt-in fallback for straight-through workers:** a configured break can set
  `auto_deduct: true` (the new `auto` column in the breaks modal:
  `name,HH:MM,duration[,leeway[,auto]]`, e.g. `Lunch,12:00,60,30,yes`) to
  restore the legacy behavior — deduct the nominal duration minus any
  clock-out gap that starts in the window — for people who do not clock out
  for breaks. **Auto-deduction is off by default**, so the headline behavior
  only ever counts real recorded break time and never double-counts.
- **Backward compatible:** `BreakConfig` gains an `auto_deduct` field
  defaulting to `False`; older config files that predate it load as `False`
  (so existing data never double-counts), and the `_extra` round-trip of the
  global config is unchanged. `BreakConfig` now also preserves unrecognized
  per-break keys via its own `_extra`, so a newer version's extra break fields
  survive a load/save round-trip (forward compat at the break level too).
  `work_report.py` stays pure (no I/O) and all
  presentation remains behind the overridable render seams.

### Added

#### Jump to top / bottom of the list (`doto tui`)
- **`Shift+Up` / `Shift+Down` now jump the cursor to the first / last entry
  of the current list in every layout.** The jump is per-layout:
  - **Table / list:** move to the first / last row.
  - **Kanban:** the first / last card of the **current swim lane**. The jump
    stays inside the focused status column — it moves the *selection cursor*,
    not the card — so switching lanes with `h` / `l` (or `←` / `→`) and
    pressing `Shift+Down` again lands on the last card of the now-current
    lane.
  - **Calendar:** the active region's first / last entry — the first / last
    day of the visible month in the grid region, or the first / last task in
    the focused `Due` / `No due date` list.
  - **Time:** the first / last day in the day list.
  Empty lists / lanes are a safe no-op.
- The feature follows the existing navigation architecture exactly: new
  app-level actions `DotoApp.action_cursor_top` / `action_cursor_bottom`
  funnel through a shared `DotoApp._jump_cursor(to_bottom)` helper (the
  jump-to-edge sibling of `_move_cursor`), the `AltLayoutView` re-binds
  `shift+up` / `shift+down` on the focused view (delegating to the app, as it
  already does for the plain arrow keys) so the bindings fire while an
  alt-view holds focus.
- **New overridable seam:** jump-to-edge is implemented as a
  `move_cursor_to_edge(to_bottom: bool)` method on `AltLayoutView`, overridden
  per view (`ListView`, `KanbanView`, `CalendarView`, `TimeView`) — the same
  convention as `move_cursor`. A child theme can retune or replace the jump
  per view by subclassing the view and swapping the `DotoApp.*_view_class`
  attribute, without touching the app.

#### Choose the target repository when adding a task (`doto tui`)
- **The add-task modal (`a`) now lets you pick which repository the task is
  created in.** Alongside the title input it shows a type-to-filter
  repository selector (the same `FilterableSelect` the edit dialog uses),
  populated from the cached repository list plus the current repo and
  defaulting to the current working directory's repo. The selector is omitted
  when only the current repo is available, so single-repo setups are
  unchanged. On submit the task is created in the chosen repo's store and the
  notification names that repo when it differs from the current one.
- `actions.add_task` gained an optional `repo: DiscoveredRepo | None = None`
  keyword: when `None` (the default) it writes to `ctx.store` as before; when
  given, it builds the target store via `data.store_for_repo(repo)` and
  generates the id against — and saves into — that store. It still reuses
  `_build_task_data` so the add logic matches `doto add`.
- The modal follows the existing overridable-seam convention: it is exposed
  as `DotoApp.add_task_screen_class` (mirroring `edit_task_screen_class`) and
  its selector widget as `AddTaskScreen.select_class` (mirroring
  `EditTaskScreen.select_class`), and the `(label, value)` option list is
  built by the pure, render-independent module-level `build_repo_options`
  helper, so a child theme can restyle or re-behave the picker by
  subclassing.

#### Calendar-view task navigation + due-date assignment
- **`Tab` navigates into the calendar's task lists**: the `calendar` layout
  now has three focus regions cycled with `Tab` (and the exact reverse with
  `Shift+Tab`) — the month grid, the selected day's **`Due` task list**, and
  the always-shown **`No due date` task list** — followed by the shared
  details pane and back to the grid. In the grid region `h`/`l` still move a
  day and `j`/`k` move a week; in the `Due`/`No due date` regions `j`/`k`
  move a per-task cursor, and moving past a list's end flows into the
  adjacent region. The highlighted task in the focused list is what
  `selected_id()` returns, so `e` (edit), `Enter`, and close/done act on
  **that** task — letting you step from a selected day straight into its due
  (or undated) tasks to edit / close / reveal them.
- **`Enter`/`e` on the `No due date` list**: focusing the `No due date`
  region surfaces the highlighted undated task, so `Enter` opens its card
  viewer and `e` edits it.
- **`A` assigns the selected day as an undated task's due date**: with a
  `No due date` task highlighted and a calendar day selected, `A` assigns
  that day as the task's `due` (routed through the single-task update path,
  so it never duplicates business logic); the task leaves the no-due bucket
  and appears under that day's `Due` list. A documented no-op (with a notify)
  when no undated task is highlighted, and a no-op in other layouts.
- The new active-region highlight flows entirely through the overridable
  `CalendarView.format_day_detail` / `format_entry` seams (the active region
  and task cursor are passed in), so a child theme can restyle the highlight
  by subclassing and swapping `DotoApp.calendar_view_class`. The calendar's
  `Tab`/`Shift+Tab` handling is wired via the data-driven `AltLayoutSpec`
  `tab_action` rather than a hard-coded per-layout branch.

#### Live interval duration + configurable work-week total (`time` layout)
- **Live `Duration` field in the "Edit work interval" pop-up**: the interval
  editor now shows a read-only `#interval-duration` field that recomputes
  `stop − start` (via `format_duration`) on every keystroke in the start/stop
  inputs, so you can nudge the stop time and watch e.g. `1h42m` become
  `1h57m` instantly. A blank stop shows `(running)` and an unparseable or
  non-positive duration shows a dim `—` placeholder (never crashing); the
  save is still validated separately. The computation is factored into the
  pure, unit-testable `interval_duration_seconds` helper.
- **Configurable "work week" net total in the summary panel**: the `time`
  layout summary panel gains a **Work week** net total — the sum of net work
  over the current week's days whose weekday is in a configurable set,
  defaulting to **Mon–Fri**. The set is stored as `workweek_days` in the
  global config (Python's Monday=0..Sunday=6 convention; sanitized to ints in
  0..6, de-duplicated, sorted, defaulting when missing/empty/invalid) and is
  editable from the **breaks + work week** modal (`b`) as `Mon-Fri` or
  `0,1,2,3,4`. The total reuses `work_report.compute_period` filtered by
  `DayWork.day.weekday()` and is rendered via a separate overridable
  `WorkTimeSummary.format_workweek` classmethod with a human-readable
  weekday-range label (contiguous → `Mon–Fri`; otherwise the days are listed).
  New pure helpers `workweek_net_seconds` and `weekday_range_label` back it.

#### Work-time summary panel + statistics pop-up (`time` layout)
- **Right-side summary panel in the `time` layout**: beside the day list, a
  `WorkTimeSummary` panel shows the gross / breaks / **net** totals for **This
  week**, **This month**, and **This year** (each anchored on today), reusing
  `work_report.compute_period` over `week_range` / `month_range` /
  `year_range` with the same breaks the day view deducts. It refreshes
  whenever intervals change (e.g. after the work-time manager closes). The
  panel is an overridable `WorkTimeSummary` widget
  (`DotoApp.work_time_summary_class`) with pure `format_*` classmethods and a
  unit-testable `summary_data` computation, so a child theme can replace its
  rendering.
- **Statistics pop-up (`S`)**: a new `WorkStatsScreen` modal opened from the
  `time` layout shows per-period numbers **and** text / ASCII block-character
  bar charts (not the SVG `charts.py` renderer). It defaults to the **day work
  length distribution per week** (one `█` bar per weekday = that day's net
  length) and supports day / week / month / year net totals, switching
  granularity with `d` / `w` / `m` / `y` (or `g` to cycle) and moving the
  anchor period with `←` / `→`. The bars are drawn by the pure, unit-testable
  `render_bar_chart` helper, and the screen is overridable
  (`DotoApp.work_stats_screen_class`).

#### Work-time manager: 2nd-session edit fix + Up/Down navigation
- **Fixed: the 2nd (and later) interval of a day could not be edited** in the
  work-time manager (`t`, or `Enter` on a day). The `#worktime-list`
  `ListView` was not focused on mount, so the highlight was stuck on row 0 and
  `e` / `Enter` only ever acted on the first interval. The list is now focused
  on mount and after every refresh, so `↑` / `↓` (and the new `j` / `k`) move
  between a day's sessions and `e` / `Enter` edit the highlighted one. The
  highlighted row index is preserved across a refresh where possible (an edit
  no longer snaps back to row 0), and the modal hint text now mentions the
  Up/Down session navigation.

#### Time-management layout view (`v` → `time`)
- **New `time` task-list layout**, cycled to with `v` alongside
  table/list/kanban/calendar and persisted as the default (`tui_layout`). It
  renders the global **work clock** rather than the task list: every day with
  one or more work-clock intervals, newest first, each listing its start/stop
  intervals and that day's **gross / auto-deducted break / net** totals, with
  a **grand total** across all shown days at the top. Break deduction reuses
  the same `doto report` math (`work_report.compute_day`), so the net figures
  agree with the CLI report. `j` / `k` (or `↓` / `↑`) move the day cursor and
  `Enter` opens the existing work-time manager modal (the `t` screen) for the
  selected day so intervals can be added / edited / deleted, with the totals
  refreshed on close — the read-oriented companion to the `t` modal.
  Implemented as a new overridable `TimeView` (`DotoApp.time_view_class`) added
  to the data-driven `ALT_LAYOUTS` registry, plus a `TuiLayout.TIME` enum
  member.

#### Kanban square cards, card viewer popup, and frame highlight
- **Framed, fixed-size square kanban cards**: each kanban card is now drawn
  as a box-framed tile constrained in **both** width and height so it reads as
  an (approximately) square card instead of a variable-height block. Because a
  terminal character cell is about twice as tall as it is wide, a visual
  square uses roughly `width / CARD_ASPECT` rows (`card_interior_rows`). Body
  text that does not fit the fixed footprint is **clipped with an ellipsis**
  (`clip_body`) rather than growing the card. The square dimension, aspect,
  row bounds, frame characters, and clip indicator are overridable `KanbanView`
  class attributes (`CARD_ASPECT`, `MIN_CARD_ROWS`, `MAX_CARD_ROWS`,
  `FRAME_CHARS`, `CLIP_INDICATOR`), and `card_height` / `cursor_line` /
  `HEADER_LINES` stay in lockstep with the new fixed layout so scroll-follow
  still lands correctly.
- **Selected card frame highlight**: the currently selected kanban card is
  marked by a highlighted **frame** (a colored border, via the overridable
  pure classmethod `frame_style` / the `SELECTED_FRAME_STYLE` / `FRAME_STYLE`
  attributes) instead of reverse-videoing the whole card.
- **Card viewer popup (`Enter`) in list, kanban, and calendar**: pressing
  `Enter` in the list, kanban, or calendar layout
  now opens a new modal **card viewer** (`CardViewerScreen`) listing the
  task's *full* content - the same fields as `doto list -f cards`
  (`format_task_detail`): id, title, assignee, priority, status, due, tags,
  depends_on, series, created, updated, and body - with the body in a
  scrollable region so a long description scrolls inside the popup. `Enter`
  again or `Escape` closes it. The viewer's detail assembly is a pure,
  unit-testable classmethod (`build_detail_lines`), and the screen is
  overridable via `DotoApp.card_viewer_screen_class` (mirroring
  `edit_task_screen_class`). The table layout keeps the
  existing shared-details-pane reveal on `Enter` (it has its own details
  pane, so the popup is not used there).
- **`e` opens Edit from the card viewer**: pressing `e` inside the card viewer
  closes the popup and opens the existing edit dialog (`EditTaskScreen`) for
  the same task; applying edits writes through the same `actions.update_task`
  flow and refreshes the board, reusing the edit path rather than duplicating
  it (shared via the new `_open_edit` helper). `e` still edits the selected
  task directly from the board as before.

#### TUI navigation, kanban layout, and smart scrolling
- **Tab advances panes in the kanban and calendar TUI layouts**: `Tab` now
  cycles focus between the active alt-view (kanban board / calendar grid) and
  the shared details pane (into details and back), mirroring the table
  layout's pane cycling. The single-pane list layout keeps focus on its view.
  `AltLayoutView` rebinds `Tab` to the app's `cycle_pane` action so Textual's
  default focus navigation no longer swallows it on a focused view.
- **Richer kanban cards with even, non-spilling columns**: each card is now a
  multi-line block whose first line shows the task **ID and due date** (a
  `(no due)` placeholder keeps the minimum width stable), with the
  description **wrapped** underneath to the column width. When the terminal is
  wide enough the card's **priority** is shown and the columns are **spaced
  evenly** across the available width; when space is tight priority is dropped
  and columns clamp to the minimum needed for the ID + due line. Every line is
  padded/truncated to its column so a card never **spills into the next
  column**. The column width, minimum, priority threshold, and placeholder are
  overridable `KanbanView` class attributes (`MIN_COLUMN_WIDTH`,
  `PRIORITY_WIDTH`, `DEFAULT_COLUMN_WIDTH`, `DUE_PLACEHOLDER`), and the
  `format_board` / `format_column` / `format_card` classmethods stay pure
  (width/priority are passed in) so a child theme can still swap rendering.
- **Calendar month grid stays pinned**: arrow / vim navigation in the calendar
  layout no longer scrolls the month grid (header + weekday legend + week
  rows) off the top. The grid is pinned and only the per-day task list below
  it scrolls, via a `CalendarView.scroll_to_cursor` override.
- **Smart, configurable scrolling for the alt-views**: the shared
  `AltLayoutView` scroll-follow now only begins scrolling when the cursor
  comes within a margin of the top/bottom of the visible frame, then jumps a
  block of rows in the move direction rather than creeping one line at a time.
  The margin (default **2** rows) and jump (default **5** tasks) are
  overridable class attributes `SCROLL_MARGIN` and `SCROLL_JUMP` on
  `AltLayoutView` (centralized in `scroll_to_cursor` / `target_scroll_y`).

#### Email view scrollable list cap
- **Configurable visible-task cap for the `doto-list` email view**: the
  top-right task list pane in `:format: email` is now scrollable and caps how
  many rows are visible at once (default **5**). Controlled by the new
  directive-level option `:visible-tasks:` (overrides the config) and the new
  `doto_list_visible_tasks` config value (default `5`, `rebuild="env"`). The
  value must be an integer `>= 0`; an explicit `0` means "show all" (no cap),
  while omitting the option falls back to `doto_list_visible_tasks`. The cap is
  a scroll viewport only — every matching task still renders and stays
  scrollable/clickable (distinct from `:limit:`, which caps how many tasks are
  included at all). Resolution lives in the Python renderer
  (`_resolve_visible_tasks`, following the `_resolve_list_icon_mode` pattern)
  and threads a plain resolved integer into the template context; the template
  emits it on `.doto-email-list` as both a `data-doto-visible-tasks` attribute
  and a `--doto-visible-tasks` CSS custom property (only for a positive cap),
  and the shipped CSS (default and minimal themes) keys off the
  `data-doto-visible-tasks` attribute to compute `max-height`, so the cap works
  as pure CSS with no new JS dependency and degrades gracefully when JavaScript
  is unavailable. Invalid (non-integer / negative) directive values are rejected
  at parse time with a clear directive error. The template and CSS remain
  child-theme overridable via `<srcdir>/_doto/templates/html/` and
  `doto_html_css_files`.

#### xlink resolution
- **Resolve `:xlink:` tokens via `sphinxcontrib-xlink`**: the task `:assignee:`
  field's value is scanned for `:xlink:`key`` tokens, each resolved to the
  referenced entity's display name at render time, linked in HTML (`<a href>`)
  and PDF/LaTeX (`\sphinxhref`) — across the single-task box and every
  `doto-list` view (table, list, cards). Only the `:assignee:` field resolves
  (which fields resolve is data-driven via `FieldDefinition.resolves_xlinks` /
  `fields.XLINK_FIELDS`; `:title:` and `:body:` render raw text). Resolution
  uses sphinxcontrib-xlink's resolver
  API (`_get_xlink_data`) and is **render-time only** — the stored RST and
  `tasks.json` keep the raw token, so bidirectional sync stays byte-stable.
  Controlled by the new `doto_resolve_xlinks` config value (default `True`;
  set `False` to always render the raw token). Degrades gracefully: when
  `sphinxcontrib-xlink` is absent or not listed in `extensions`, the raw token
  is rendered unchanged (no crash). All xlink knowledge lives in the new
  `doxtr_doto.xlink` module with a documented, overridable resolver seam
  (`_get_resolver_fn`) and token regex (`XLINK_TOKEN_RE`) for child themes. A
  new optional `xlink` extra (`pip install "doxtr-doto[xlink]"`, folded into
  `all`) pulls in the dependency for convenience; it is never a hard dependency.

#### Task-list layout views
- **Configurable `doto-list` layout views (`:format:` kanban / calendar /
  email)**: the `.. doto-list::` directive's `:format:` option now accepts
  three new HTML-interactive layouts in addition to `table`/`list`/`cards`:
  - `kanban` — columns by status with cards draggable between columns.
  - `calendar` — a month grid placing tasks on their due date; click a day to
    reveal that day's tasks (undated tasks shown in an "unscheduled" bucket).
  - `email` — a three-pane layout (status tree left, task list top-right,
    selected-task detail bottom-right).
  The interactions are driven by a vendored, dependency-free JS asset
  (`doto-views.js`, registered via `app.add_js_file` for HTML builders only and
  copied to `_static`). Because a static Sphinx build has no backend, kanban
  drag / calendar click / email selection are **client-side and visual only**
  (not persisted). Each view ships a child-theme-overridable Jinja2 template
  (`doto-list-kanban.html`, `doto-list-calendar.html`, `doto-list-email.html`
  with documented context blocks) plus matching Jinja-less fallback renderers,
  and namespaced CSS in both bundled themes (`doto-kanban-*`, `doto-calendar-*`,
  `doto-email-*`). The `ListFormat` enum gained `KANBAN`/`CALENDAR`/`EMAIL`
  (kept in sync with the directive's `VALID_FORMATS`). LaTeX/epub builds degrade
  gracefully: calendar falls back to the table rendering and kanban/email to
  the grouped description-list rendering, never crashing.

#### Archiving
- **`doto-archive` directive**: a new `.. doto-archive::` directive renders the
  archived-task page directly from the JSON task store (id, title, status,
  priority, assignee, archive date, original page, body). It goes through the
  node + template/theme system (new `doto_archive_node` + `doto-archive.html`
  template with a Jinja-less fallback), so a child theme can override it via
  `_doto/templates/html/doto-archive.html`. The virtual archive page now emits
  this directive instead of a plain `doto-list`.
- **Restore-to-place on reopen**: when a task is archived, a restore anchor
  (preceding source context + the removed directive + the original page title)
  is captured into the task's JSON `_sync._archive` block. Reopening a task
  re-inserts its directive into the original RST file at the same location.
  If the file was heavily modified (the anchor no longer matches uniquely) the
  directive is placed at the top of the page instead. If the original page was
  renamed or deleted, the reopen fails for that task with a message naming the
  original page title and path (no silent relocation to the inbox). New
  `doxtr_doto.sync.restore` module with `restore_task_to_rst`, `RestoreResult`,
  and `RestorePath`; new `capture_restore_anchor`/`extract_page_title` helpers
  in `rst_writer`. Surfaced from both the CLI `doto reopen` command and the
  build-time reopen path.

#### Interactive TUI
- **`Shift+Tab` cycles TUI panes in reverse; the active kanban lane is
  colored**: `Shift+Tab` now walks the *exact reverse* of the forward `Tab`
  pane cycle in every layout - table (repo tree → details → task list),
  kanban (step to the previous swim lane, wrapping first lane ↔ details ↔ last
  lane), calendar (the same view ↔ details toggle in reverse), and a no-op
  (refocus) in the single-pane list layout. The forward `Tab` behavior is
  unchanged; both directions share one implementation per layout via a signed
  `direction` argument (`DotoApp._cycle_pane` / `_cycle_kanban_lanes` /
  `_focus_next_in_cycle`), and the details pane and alt-views rebind
  `shift+tab` to the app so Textual's default focus traversal does not swallow
  it. Independently, the **active (focused) kanban lane** is now shown by
  coloring its column **header** and - when the lane is empty - its `(empty)`
  placeholder with the overridable `KanbanView.ACTIVE_COLUMN_STYLE` (new pure
  `format_header(..., focused=...)` / `format_empty_placeholder(focused=...)`
  classmethods), so the active lane is always visible even when it holds no
  card and so has no highlighted card frame to mark it. The accent is pure
  markup that occupies no screen columns, so coloring never changes a column's
  computed width or the board alignment. Extends `tests/cli/test_tui.py`.
- **Configurable task-list layout views (`v`)**: the `doto tui` task list now
  cycles between four layouts with `v` - `table` (the existing default 3-pane
  table), `list` (a single compact column, one task per line, with
  Enter-to-detail), `kanban` (tasks grouped into columns by status from
  `ctx.config.statuses`, with a trailing `(other)` column for unexpected
  statuses), and `calendar` (a month grid placing tasks on their due date with
  an always-shown "no due date" bucket for undated/unparseable-due tasks).
  Kanban "move between columns" is implemented as the **terminal
  drag-equivalent** keyboard move (`h` / `l` move the selected card to the
  previous / next status column), routed through the same `actions.update_task`
  path as every other mutation so business logic is never duplicated; calendar
  `h` / `l` select the previous / next day (`j` / `k` move a week). The chosen
  layout is **persisted** as the user's default in global state
  (`GlobalState.tui_layout`) via `actions.save_tui_layout` /
  `actions.load_tui_layout`, backward compatible (absent/unknown values fall
  back to the table view). A new `TuiLayout` enum (separate from the directive
  `ListFormat`) names the views; each view is its own overridable widget
  (`ListView`, `KanbanView`, `CalendarView`) with pure `format_*` / bucketing /
  move classmethods, sharing an `AltLayoutView` base so the app drives every
  alt-view through a single data-driven registry (one row per layout) and a
  single CSS selector, registered on `DotoApp` via `list_view_class`,
  `kanban_view_class`, `calendar_view_class` so a child theme can replace any
  view's rendering by subclassing. Does **not** touch the `doto-list`
  directive's `:format:` layout views. Extends `tests/cli/test_tui.py` and
  `tests/test_enums.py`.
- **Elapsed-time display (day total + session + current task)**: the TUI now
  shows a right-aligned, top line with the whole day's accumulated **work
  time** (summed across all of today's work-clock intervals) and the current
  **work session** - the time of the work-clock interval open right now -
  shown in parentheses after it (omitted when no session is open), plus the
  **total time spent on the currently highlighted task** (summed across all
  of that task's worklogs). It refreshes on the same live timer as the status
  line and updates immediately as the task-list cursor moves. The daily total
  and current-session time come from `data.live_counters` /
  `data.current_work_session_seconds` (built on `session.live_focus_elapsed`),
  the per-task total is a new pure, unit-testable `data.task_total_seconds`
  helper (built on `time_tracking.elapsed_seconds`), and the rendering is a
  new overridable `TaskTimeLine` widget with a pure `format_times` classmethod
  (swappable via `DotoApp.task_time_line_class`).
- **Editable due date in the edit dialog**: the edit dialog (`e`) now includes
  a Due field that accepts the same absolute (`YYYY-MM-DD`) and relative
  (`+7d`, `+2w`, `today`, `friday`, `next-monday`, ...) forms as
  `doto update --due`, parsed with the very same
  `doxtr_doto.cli.commands.add.parse_relative_date` helper (exposed as
  `EditTaskScreen.parse_due`) so the CLI and TUI never diverge. Leaving it
  empty clears the due date; an invalid date is reported inline and keeps the
  dialog open rather than writing a corrupt value. The update persists through
  the existing `actions.update_task` path (same as `doto update`), preserving
  RST↔JSON sync, and only changed fields are included in the updates dict.
- **Bash-style kill/yank across the edit dialog**: the edit dialog (`e`) now
  shares a single kill ring across all its text fields. `Ctrl-K` deletes from
  the cursor to the end of the line and captures the removed text; `Ctrl-Y`
  yanks (re-inserts) it at the cursor. Because the kill ring is shared, text
  killed in one field can be yanked into another - e.g. kill the Title with
  `Ctrl-K` and paste it into the Body with `Ctrl-Y`, or vice-versa. The Title,
  Assignee and Tags inputs use a new `KillRingInput`, and the Body uses a new
  `KillRingTextArea`, both backed by a shared `KillRing`. An empty kill at
  end-of-line preserves the existing buffer. The input and text-area widgets
  are overridable from a child theme via `EditTaskScreen.input_class` /
  `EditTaskScreen.text_area_class` (mirroring `select_class`), the keybindings
  are documented in the README edit-dialog section, and the in-app help modal
  (`?`) lists them.
- **Edit modal (`e`)**: opens an `EditTaskScreen` to edit the selected task's
  title, priority, status, assignee, tags, due date, and body, pre-populated
  from the current values. On submit the changes route through a new
  `actions.update_task`, which mirrors the single-task path of `doto update`
  (`resolve_task_ref` + `store.update_task` + `store.save`).
- **Edit modal type-to-filter + scrolling body**: in the edit dialog, the
  Priority and Status fields now support type-to-filter / letter-select -
  typing letters narrows and/or selects a matching option using word-based
  prefix matching (e.g. `progress` finds `in-progress`, `c` selects
  `critical`). The matching is implemented by a pure, unit-testable helper
  (`doxtr_doto.cli.tui.app.filter_options`) backing a new overridable
  `FilterableSelect` widget (swappable via `EditTaskScreen.select_class`).
  The Body field is now a scrolling, soft-wrapping `TextArea` (Enter inserts
  a newline instead of submitting) and the `Save` button is docked at the
  bottom of the modal so it stays visible while scrolling.
- **`d` / `D` status keys**: `d` marks the selected task(s) done (reusing
  `actions.complete_task`); `D` cycles the status to the next value in the
  configured cycle (`statuses`, falling back to the built-in display
  order) via a new `actions.cycle_status`, wrapping around at the end.
- **`Space` multi-select**: `Space` now selects / deselects the current task
  (tracked in `TaskList.selected_ids` and marked in the list) instead of
  completing it. When a multi-selection is active, `d` and `D` operate on all
  selected tasks and then clear the selection; otherwise they act on the
  single cursor task. A new `TaskList.target_ids` returns the effective
  target list. The help modal and README keybinding table were updated
  accordingly.

### Changed
- **Kanban navigation / card-move keys switched** (interactive TUI): in the
  kanban layout the arrow keys (and `h`/`l`) now navigate the *selection*
  across swim lanes **exclusively** - they no longer move a card - and
  `Tab`/`Shift+Tab` now **move the selected card** one lane forward/back (the
  status change previously bound to the arrows). The card-move routes through
  the existing single `doto update` path (`move_target_status` ->
  `actions.update_task`) and is a no-op at the board edges / into the
  `(other)` lane. The switch is scoped to kanban only: the table, list, and
  calendar layouts keep their existing `Tab`/arrow semantics. `Tab`/`Shift+Tab`
  dispatch is now data-driven through a new overridable `AltLayoutSpec`
  `tab_action` hook (not a hard-coded per-layout branch), so a child theme can
  rebind kanban key behavior without rewriting app logic. README and in-app
  help text updated to match.
- **Overridable directive-rendering seam** (`register_directive_renderer` /
  `render_directive_text` / `reset_directive_renderer` in
  `doxtr_doto.sync.rst_writer`): RST directive-text generation now routes
  through a single indirection point so a downstream/child theme can replace
  ALL `.. doto::` directive rendering with its own
  `(task_data) -> rst text` implementation without editing core (mirroring the
  `doxtr_doto.xlink` resolver seam and the restore-strategy registry).
  `generate_directive_text` remains the built-in default. Additive export;
  behavior preserved when no renderer is registered.
- **Core-internal light-palette access is isolated behind a single overridable
  seam** (`doxtr_doto.integration._core_light_palette_defaults`): the two
  `doxtr-pdf-theme-core` internals the merge needs
  (`core_config.DOXTR_SEMANTIC_PALETTE` and `utils.deep_update`) are now reached
  from exactly one place, so a child theme or a future public-core accessor can
  redirect the merged light palette's source with a one-function change.
  Additive export; behavior preserved (internal refactor, no runtime behavior
  affected).
- **Formatting is now managed by `ruff format`** and the `dev` extra pins
  `ruff==0.16.9` so every contributor produces identical output. The source
  tree was reformatted in one pass; CI enforces `ruff format --check` and
  `ruff check` (internal/dev-tooling change, no runtime behavior affected).
- **Auto-archive is now on by default** (`doto_auto_archive = True`). Completed
  tasks (matching `doto_archive_statuses`) are removed from their RST file,
  preserved in JSON, and shown on the archive page. Set `doto_auto_archive =
  False` to keep completed tasks inline. `doto reopen` now reports which
  restore path was taken per task and surfaces the renamed/deleted-page error.

### Fixed

#### Multi-repo registry
- **Nested doto repositories are now discovered**: `doto repos rescan`
  (`RepoRegistry.discover`) previously stopped descending once it found a
  directory containing `.doto/tasks.json`, so a doto repo nested inside
  another repo was never cached. The walk now keeps descending into a
  repository's non-pruned, non-gitignored children, so inner repos are
  discovered and namespaced alongside the outer one. The repo's own `.doto/`
  directory is pruned so it is never walked or mistaken for a nested repo.

#### Directives
- **Multi-line `.. doto::` titles no longer break the `doto tui` list view**:
  a directive title written across indented continuation lines (e.g. a long
  title wrapped over two or three lines) kept the embedded newlines and
  continuation indentation, because the directive only `.strip()`-ed the
  argument. The stored title therefore contained `\n   ` sequences, which
  broke the `doto tui` list-view layout and scroll behaviour (the list view
  renders the raw title into a single compact line) and leaked into the other
  renderers (HTML/PDF, JSON export, CLI). The directive now normalizes the
  title through a reusable `doxtr_doto.utils.normalize_whitespace` helper,
  collapsing every run of whitespace to a single space and stripping the ends,
  so the stored title is always a single logical line.

#### Interactive TUI
- **Selected kanban card no longer lags behind and scrolls off-screen**: the
  shared smart-scroll treated the cursor as a single content line, but kanban
  cards are fixed multi-line blocks, so a tall selected card's bottom edge
  could drop below the viewport (moving down) and - in a small viewport - its
  bottom edge could drop below the frame moving up, as the card neared an
  edge. `AltLayoutView` now exposes a `cursor_span()` hook (the full card
  height for kanban, `1` for the list/calendar) and `target_scroll_y` keeps
  the *whole* selected item on screen by clamping the scroll target so both
  the item's top and bottom lines stay visible, symmetrically on up and down
  moves. An oversized card (taller than the viewport) aligns its top to the
  viewport top. The one-line list/calendar scroll behavior is unchanged.
- **Kanban board no longer spills under its first lane when a vertical
  scrollbar is shown**: `_available_width` used `size.width`, which still
  counts the columns a vertical scrollbar consumes, so when a lane held enough
  cards to force the view's scrollbar the board row
  (`count * col_width + gaps`) was 1-2 cells too wide and Textual soft-wrapped
  it - the rightmost lane's card frame spilled under the leftmost lane. It now
  uses the scrollbar-aware `scrollable_content_region.width` (the content area
  after the scrollbar is subtracted), which equals `size.width` when no
  scrollbar is shown, so the board row always fits and never wraps. A
  scrollbar that toggles mid-session (a lane growing past the scroll
  threshold) does not change the view's outer region - so Textual posts no
  resize - and is handled by a `watch_show_vertical_scrollbar` hook that
  re-renders the board at the new usable width.
- **Kanban lanes no longer collapse to a 2-column grid after completing a
  task**: pressing `d` (done) in the kanban layout could rebuild the board
  while the view momentarily reported a zero width, so `column_width` fell
  back to the natural wide width, overflowed the viewport, and wrapped the
  lanes into a stacked 2-column grid until the next resize. `_available_width`
  now caches the last positive live width (`_last_live_width`) and reuses it
  when a mounted rebuild sees a width of 0, so the dynamically-correct lane
  count (derived from `ctx.config.statuses`) stays stable across a completion.
- **Kanban lanes stay side by side; long IDs are middle-truncated**: the
  kanban board no longer wraps its status columns into a stacked 2x2 grid when
  task IDs are long. Previously `column_width` clamped each lane *up* to the
  widest natural `ID + due` first line (`min_card_width`), so with long IDs
  the total board row (`count * width + gaps`) exceeded the viewport and the
  containing `Static` line-wrapped every board row - visually dropping lanes
  3-4 below lanes 1-2. The per-column width is now derived from the available
  viewport width **first** (an even split across the lanes, less the
  inter-column gaps), floored only at the absolute `MIN_COLUMN_WIDTH`, so the
  whole board row always fits and every configured status renders as its own
  side-by-side lane. When a lane cannot hold a card's natural **ID** at that
  width the ID is **middle-truncated** - head and tail kept, the middle
  replaced by a single ellipsis (`ABCDEFGH-1234567` → `ABCD…4567`) - instead
  of widening the column past the viewport or clipping the ID's
  (often disambiguating) tail from the end. ID shortening is a new pure,
  overridable `KanbanView.truncate_id` classmethod with its own
  `ID_ELLIPSIS` knob, so a child theme can restyle ID truncation alone without
  touching the layout math; the title/description body keeps its existing
  **end**-clip behavior (`clip_body` / `CLIP_INDICATOR`). The width-math
  invariants (`cursor_line` / `card_height` / `format_card` / `min_card_width`)
  stay in lockstep.

- **Kanban lanes line up on first mount (no key press needed)**: the kanban
  board previously rendered as a stacked 2-column grid when the TUI first
  opened in the kanban layout, snapping into correct side-by-side lanes only
  after the first arrow key. At first mount Textual has not finished its
  initial layout pass when `on_mount` calls `rebuild`, so the view's
  `size.width` was still 0 and the columns fell back to their natural (wide)
  width - overflowing the viewport. `KanbanView` now re-renders from its
  cached columns on `on_resize` (the geometry-compute + render tail of
  `rebuild` is factored into `_render_board`), so the lanes lay out at the
  real viewport width as soon as the size is known, with no card re-bucketing.

- **`Shift+Tab` reverse cycling works in real terminals**: reverse pane
  cycling was bound only to the `shift+tab` key name, but many terminals
  deliver the physical Shift+Tab as the literal `back_tab` key, so reverse
  cycling was silently dead there (unit tests masked it because Pilot injects
  the already-normalized key name). The reverse-cycle actions are now bound to
  **both** `shift+tab` and `back_tab` at the app level and on the `TaskDetails`
  / `AltLayoutView` panes, so `Shift+Tab` cycles panes in reverse regardless
  of which key name the terminal sends.

- **TUI navigation, activation, scrolling, and kanban layout fixes**: four
  usability regressions in the task-list layout views are resolved. (1) Arrow
  keys now navigate every layout (`↑`/`↓`/`←`/`→` mirror the existing
  `j`/`k`/`h`/`l` keys): the table layout's `DataTable` and the
  list/kanban/calendar `AltLayoutView`s each bind the arrows (the alt views
  re-bind them to override the embedded `VerticalScroll`'s native scroll
  actions). (2) `Enter` reveals the selected task's details in *every* layout,
  not just the list view — the table layout routes through a
  `DataTable.RowSelected` handler (the table consumes `Enter`), while the alt
  views route through the shared `action_activate`/`_current_selected_id`
  path. (3) The alt-view layouts now scroll to keep the highlighted row
  visible: `AltLayoutView` wraps its rendered content in a scrollable
  container and follows the cursor via the overridable `cursor_line()` /
  `scroll_to_cursor()` seam (list, kanban, and calendar). (4) Kanban status
  columns now render left-to-right like a real board (previously the columns
  were stacked vertically): `format_board` lays the per-column blocks side by
  side using the overridable `format_column` / `pad_cell` classmethods and the
  tunable `COLUMN_WIDTH` / `COLUMN_GAP` class attributes. All views stay
  modular and overridable — rendering remains in pure `format_*` classmethods
  and the views are swappable via `DotoApp.{task_list,list_view,kanban_view,
  calendar_view}_class`.

- **Multi-line task titles no longer orphan the option block or re-insert the
  directive every build**: a title that spanned multiple source lines (e.g. a
  long title hard-wrapped in the RST) was emitted with the newline verbatim, so
  docutils kept only the first line as the directive argument and reinterpreted
  the remainder as body text, orphaning the following `:id:`/option block. The
  directive then failed to round-trip, the task looked missing, and the sync
  step re-inserted a duplicate `.. doto::` on every build. The title is now
  always emitted as a single "endless" line (manual line breaks within a
  paragraph are collapsed to spaces, since the editor/view wraps long lines),
  so the argument and its options always round-trip. A title that contains a
  genuine paragraph break (a blank line) has its trailing paragraph(s)
  relocated into the directive body, where multi-line content is valid reST
  (prepended ahead of any existing body so nothing is lost).
- **Hand-deleting a `.. doto::` directive from an RST source now archives the
  task instead of re-inserting it**: a JSON task that once had a directive in
  an RST file (tracked by its `_sync.rst_hash`) and whose directive the user
  then removed by hand was previously treated as missing from RST and
  re-inserted on the next build, undoing the deletion. Such a task is now
  honoured as a deletion: it is marked `done` and archived (not re-inserted),
  so it drops off active lists and appears on the archive page. CLI-created
  tasks that were never in RST (empty/missing `rst_hash`) are still created in
  RST as before.
- **Multi-directive write-back no longer corrupts the RST on `doto done`**:
  marking several tasks done in one file (so several `SyncAction.UPDATE`s are
  queued for it) could produce a duplicate `:id:` on a directive and strip the
  blank line between directives, making them run together. Three root causes
  were fixed: (1) queued line-based updates (`UPDATE` / `INSERT_ID`) are now
  applied bottom-to-top (descending `_rst_line`) so injecting an `:id:` into
  one directive no longer invalidates the stale line numbers of the ones
  below it; (2) the `:id:` is dropped from an update's applied options unless
  the directive is genuinely bare (verified by an authoritative whole-file id
  lookup, not a slice-local regex), so an existing id is never duplicated; and
  (3) an empty-body update preserves the directive block's structural trailing
  newline, so a directive with no body is no longer merged into the next one.
- **Status/field edits now sync into bare directives (no `:id:`)**: a
  directive written without an explicit `:id:` option gets an auto-generated
  `{docname}-L{lineno}` id, but the write-back `SyncAction.UPDATE` located the
  directive *only* by `:id:`. When the RST directive had no `:id:` (e.g. a
  hand-written `.. doto::` with just a title and `:assignee:`), a `doto done`
  (or any JSON edit) produced no RST change at all — the UPDATE silently
  matched nothing, so the rendered page kept showing the old status. The
  UPDATE now falls back to the directive's line number when no `:id:` matches,
  and injects the `:id:` as the first option while applying the update, so the
  directive becomes self-identifying and future syncs match it directly.
  Internal `_`-prefixed keys (e.g. `_rst_line`) are never emitted as options.
- **RST write-back no longer corrupts the directive on update**: a
  JSON-only edit (e.g. from the TUI) synced back into the RST via
  `SyncAction.UPDATE` passed the full merged task dict to
  `_update_directive_content`, which treated every field as a directive
  option. It emitted bogus `:title:`/`:body:` options (title is the
  `.. doto::` argument and body is the indented content block, not options)
  and inserted new options after the blank line, i.e. into the body —
  producing a malformed directive that stopped rendering the change. The
  updater now rewrites the title on the `.. doto::` argument line, replaces
  the body as the content block (add/change/clear) via a new
  `_replace_directive_body` helper, and updates/inserts every other field as
  an option within the option block, leaving `:id:` untouched. TUI/CLI edits
  to a task's status, body, etc. now sync cleanly into both the RST source
  and the rendered page.
- **RST write-back no longer crashes on env-dependent directives in the
  file**: during a build, Sphinx registers its directives (e.g. `toctree`)
  into the global docutils registry; several read `self.env` in `run()`. The
  write-back parses RST with a standalone, env-less docutils parser, so any
  such directive in a file being updated raised
  `AttributeError: 'Values' object has no attribute 'env'`, aborting
  `SyncAction.UPDATE` for that file. The earlier fix only stubbed the `doto*`
  directives; this generalizes it by temporarily scoping the global
  directive/role registries to just the env-free doto stubs for the duration
  of each standalone parse, so every other directive/role resolves as
  "unknown" (a harmless parse-time message) instead of running env-dependent
  code. The original registries are restored afterwards.
- **Stable auto-generated IDs for bare `.. doto::` directives**: a bare
  directive (no explicit `:id:`) receives an auto-generated
  `{docname}-L{lineno}` ID at collection time. Previously that generated ID
  was persisted to `.doto/tasks.json` but never written back into the RST
  file, so a line-number shift on a later build produced a new ID, orphaned
  the existing JSON task, and recreated it as a duplicate. The sync step now
  writes the generated `:id:` back into the existing directive (via a new
  `SyncAction.INSERT_ID` RST update and the
  `rst_writer.insert_id_into_directive_at_line` helper), making the ID stable
  so subsequent builds reuse it and no longer recreate the task.

## [0.1.1] - 2026-10-02

### Added

#### Time tracking & work clock
- **Dual-layer work clock**: `doto start` clocks in and starts a global work
  clock (Layer 1); `doto start <task>` additionally starts a per-task focus
  timer (Layer 2). `doto stop` pauses the focus timer, `doto stop work` (alias
  `doto clock-out`) stops both. `doto status` shows the active focus task and
  today's work clock; `--json` emits a machine-readable form.
- **Session interval log**: `doto log [<task>]` lists a task's work intervals
  (including a live row for the running session), with `--day` filtering and
  `--fix close` recovery of unclosed/overnight sessions. Overnight sessions are
  split at midnight.
- **`complete`** registered as an alias of `done`.
- New pure helpers in `time_tracking.py` (`elapsed_seconds`, `open_session`,
  `detect_overnight`, `close_session`, `split_at_midnight`, etc.) and
  presentation helpers in `cli/session.py` (`format_duration`, `render_status`,
  `render_log`, `live_focus_elapsed`).

#### Multi-repo views & namespaced IDs
- **Repository registry**: `doto repos` (list), `rescan`, `add`, and `forget`
  manage a cached registry of discovered doto repositories, respecting
  `.gitignore` and pruning stale entries. Stored in the global config.
- **Aggregated views**: `doto list -r/--recursive` aggregates tasks across
  cached repos as `repo#id`; `--rescan` rediscovers first. `done`, `show`,
  `update`, and `start` accept namespaced `repo#id` references from any
  directory (`cli/id_resolver.py`, `cli/display.py` scope handling).

#### Global state
- **`~/.config/doto/config.json`**: XDG-aware, path-overridable, atomic global
  state (`GlobalState`/`GlobalStateStore`) holding the repository registry,
  favorites, active focus session, the dual-layer work clock worklogs, and
  `last_prompt_date`. Task data gained a `worklogs` field; `SCHEMA_VERSION`
  bumped to 5.

#### Interactive TUI
- **`doto tui`**: optional 3-pane terminal UI built on Textual (install via the
  new `tui` extra, `textual>=0.60`, also included in `all`), with live
  work/focus timers, Vim-style keybindings, and Global/Local scope. Rendering
  is modular and subclassable (`RepoTree`, `TaskList`, `TaskDetails`,
  `StatusLine` + `DotoApp.*_class` hooks). Prints an install hint when
  `textual` is absent.
- **Daily kickstart nudge**: a once-per-day startup modal (suppressed when a
  focus timer is already running) offering top-priority candidate tasks (ranked
  like `doto next`), a general work clock-in, search, or skip. Any choice
  records `last_prompt_date` so it fires at most once per day. Decision logic
  lives in a unit-testable `cli/tui/nudge.py` separate from the modal.

#### Documentation
- README documents all new commands, keybindings, the kickstart nudge, the
  global `~/.config/doto/config.json`, and the `tui` install extra.

### Changed

- **BREAKING:** `doto list -r` now means `--recursive` (aggregate tasks across
  all cached repos as `repo#id`), not `--reverse`. The `--reverse` sort flag no
  longer has a `-r` short form; use the long `--reverse` option instead.

## [0.1.0] - 2026-09-30

Initial release of doxtr-doto.

### Added

#### Core
- Initial implementation of doxtr-doto Sphinx extension
- Task directives with metadata (priority, status, assignee, due date, tags, dependencies)
- Task lists and summaries with filtering and sorting
- Cross-references with `:doto:` role
- Bidirectional sync with JSON storage
- Auto-archiving of completed tasks
- CLI tool for task management
- HTML and LaTeX theming

#### PDF / LaTeX rendering enhancements
- **Redesigned PDF task boxes**: high-contrast title bar (readable white bold title on a filled bar) with dark body text on a light background, fixing the previous white-on-white empty-box rendering. Priority-colored box variants (`dotoboxlow/medium/high/critical`) are now selected per task.
- **Stacked Font Awesome metadata icons**: task metadata (ID, priority, status, assignee, due, created, updated, tags) renders a Font Awesome icon stacked above its label. Icons degrade gracefully when no Font Awesome package is loaded, and work under Sphinx's fontawesome7.
- **Clickable PDF cross-references**: `:doto:` references emit a matching label/anchor so the generated hyperlink jumps to the task box (eliminates "undefined hyperref" warnings).
- **Task-list icon modes**: new `doto_list_icon_mode` config (`icon` | `icon-text` | `text`, default `icon-text`) plus a per-directive `:icon-mode:` override on `.. doto-list::`. Task IDs and titles in every list format are clickable links to the task. Field/value icons are overridable via the new `doto_list_icons` config.
- **doto-summary charts**: real chart visualizations for task state (`bar`, `pie`, `stacked-bar`, `progress`, `burndown`). New `doto_chart_engine` config (`svg` default | `plotly`). PDF always renders a native TikZ chart when plotly/kaleido/Chrome are unavailable; HTML falls back to inline SVG.

#### doxtr-pdf-theme-core integration
- **Semantic colors**: when `doxtr-pdf-theme-core` is active, doto's priority/status/box colors are derived from the core's merged semantic palette (core defaults → theme → user `doxtr_semantic_palette`) via the `dd:` expression system and emitted as LaTeX `\definecolor` overrides. Brand keys such as `primary`/`danger` resolve from core/theme defaults even when the user overrides only some (or no) keys. Standalone builds keep the built-in defaults. Core-internal light-palette access is isolated behind a single overridable seam (`doxtr_doto.integration._core_light_palette_defaults`) so a child theme or a future public-core accessor can redirect the merged light palette's source with a one-function change.
- **Auto-landscape tables**: wide doto task tables (column count >= the core's `doxtr_landscape_min_columns`, default 4) are automatically rotated to landscape when the core is active. Standalone output is unchanged.

#### Earlier work
- **Delete Command**: New `doto delete` command for permanently removing tasks with filter support (`--filter-status`, `--filter-priority`, `--filter-assignee`, `--filter-tags`, `--filter-archived`), dry-run mode, and series membership warnings
- **Bulk Update Operations**: Extended `doto update` command with filter options (`--filter-status`, `--filter-priority`, `--filter-assignee`, `--filter-tags`, `--filter-overdue`) for bulk task updates with `--all` safety flag, `--dry-run` preview, and `--yes` confirmation skip
- **Sphinx Domain**: Added `DotoDomain` for proper Sphinx integration with `:doto:task:` role syntax and intersphinx support
- **epub Theme Support**: Added epub-specific themes (`default`, `minimal`) optimized for e-readers with `page-break-inside: avoid`
- **Theme Auto-Discovery**: Automatic discovery of custom themes from project's `_doto/` directory (html, latex, epub)
- **pdf-theme-core Integration**: ThemeRegistry pattern integration with doxtr-pdf-theme-core when available
- **Virtual Archive Document**: Proper temporary file creation and cleanup for archive documents
- **LaTeX Column Specs**: Configurable column specifications via `doto_latex_column_specs`
- **Date Utilities**: Added `normalize_date()`, `parse_date_safe()`, `format_date_display()` for consistent date handling

#### Security
- **HTML Escaping**: Added `escape_html_attr()`, `escape_html_content()`, `sanitize_html_id()` utilities
- **Path Traversal Prevention**: Added `validate_path_within()` to prevent path traversal attacks in sync operations
- **Config Security**: Enhanced `load_sphinx_config()` with security documentation and better error handling

#### Testing
- Added 95+ new tests covering epub output, RST writer edge cases, validation, parallel builds, CLI commands, and security
- Total test count: 1381 tests passing

#### CI
- **Circular-Import Check**: Run `scripts/check_imports.py` (circular-import detection) before pytest in both `test.yml` and `test-harness.yml`

### Changed

#### Code Quality
- **Coverage Gate**: Enforce a coverage gate via pytest addopts (`--cov=doxtr_doto --cov-fail-under=80`) in `pyproject.toml`, so local `python -m pytest` and CI share a single source of truth for the threshold
- **JsonTaskStore**: Consolidated duplicate implementations - CLI now re-exports from sync module
- **Type Safety**: Created `types.py` with `DotoSyncData` TypedDict, `DotoExtendedEnv` Protocol, and type-safe accessor functions
- **Error Handling**: Added custom exception hierarchy (`DotoError`, `DotoSyncError`, `DotoConflictError`, `DotoRstWriteError`, `DotoValidationError`)
- **RST Writer**: Removed global state, now uses docutils' built-in directive registry
- **Constants**: Replaced magic strings with constants from `constants.py` throughout codebase
- **Function Refactoring**: Extracted helper functions from `perform_bidirectional_sync()` for better maintainability
- **Docstrings**: Added Google-style docstrings with Args/Returns/Raises to all public functions
- **`__all__` Exports**: Added proper `__all__` definitions to all package `__init__.py` files

### Fixed

- Fixed RST-only `.. doto::` directives (no explicit `:id:`, auto-generated `{docname}-L{lineno}` ID) not being persisted to `tasks.json` during sync; they were silently dropped and never appeared in `doto list` or other CLI commands. New RST tasks are now created in the JSON store on first sync.
- Fixed potential `AttributeError` in `_update_directive_content` when regex match returns None
- Fixed input validation in RST writer functions (`_find_directive_block`, `update_doto_directive`, etc.)
- All HTML output now properly escapes user-provided content to prevent XSS
- All LaTeX output consistently uses `_latex_escape()` for special characters

### Deprecated

- The `missing-reference` handler is retained for backward compatibility but domain-based resolution is preferred

