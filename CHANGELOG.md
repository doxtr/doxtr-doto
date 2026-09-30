# Changelog

All notable changes to doxtr-doto will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **Semantic colors**: when `doxtr-pdf-theme-core` is active with a `doxtr_semantic_palette`, doto's priority/status/box colors are derived from the palette (via the `dd:` expression system) and emitted as LaTeX `\definecolor` overrides. Standalone builds keep the built-in defaults.
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

- Fixed potential `AttributeError` in `_update_directive_content` when regex match returns None
- Fixed input validation in RST writer functions (`_find_directive_block`, `update_doto_directive`, etc.)
- All HTML output now properly escapes user-provided content to prevent XSS
- All LaTeX output consistently uses `_latex_escape()` for special characters

### Deprecated

- The `missing-reference` handler is retained for backward compatibility but domain-based resolution is preferred

