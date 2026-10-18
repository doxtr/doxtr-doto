"""Tests for template_loader module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockTask:
    """Mock task object for testing."""

    id: str = "TASK-001"
    title: str = "Test Task"
    priority: str = "high"
    status: str = "open"
    assignee: str | None = "alice"
    due: str | None = "2024-01-15"
    tags: list[str] | None = None
    depends_on: list[str] | None = None
    progress: int | None = None
    estimate: int | None = None
    created: str | None = None
    updated: str | None = None
    _is_overdue: bool = False

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.depends_on is None:
            self.depends_on = []

    def is_overdue(self) -> bool:
        return self._is_overdue


class TestJinja2Availability:
    """Tests for Jinja2 availability detection."""

    def test_jinja2_available_flag_is_boolean(self):
        """JINJA2_AVAILABLE should be a boolean."""
        from doxtr_doto.template_loader import JINJA2_AVAILABLE

        assert isinstance(JINJA2_AVAILABLE, bool)

    def test_jinja2_is_available_in_test_env(self):
        """Jinja2 should be available in the test environment."""
        from doxtr_doto.template_loader import JINJA2_AVAILABLE

        # Jinja2 is in dev dependencies, so should be available
        assert JINJA2_AVAILABLE is True


class TestGetTemplateDirs:
    """Tests for get_template_dirs function."""

    def test_returns_bundled_dir_when_no_srcdir(self):
        """Should return bundled templates dir when srcdir not provided."""
        from doxtr_doto.template_loader import get_template_dirs

        dirs = get_template_dirs()
        assert len(dirs) >= 1
        assert dirs[-1].name == "html"
        assert "templates" in str(dirs[-1])

    def test_returns_bundled_dir_when_srcdir_has_no_override(self, tmp_path):
        """Should return only bundled dir when project has no override dir."""
        from doxtr_doto.template_loader import get_template_dirs

        # Use a fresh tmp_path with no _doto directory
        srcdir = tmp_path / "project"
        srcdir.mkdir()

        dirs = get_template_dirs(srcdir=srcdir)
        assert len(dirs) >= 1
        # No project override dir should be included
        assert not any(str(d).startswith(str(srcdir)) for d in dirs)

    def test_returns_project_dir_first_when_exists(self, tmp_path):
        """Should return project override dir first when it exists."""
        from doxtr_doto.template_loader import get_template_dirs

        # Create project override directory
        project_tmpl = tmp_path / "_doto" / "templates" / "html"
        project_tmpl.mkdir(parents=True)

        dirs = get_template_dirs(srcdir=tmp_path)
        assert len(dirs) >= 2
        assert dirs[0] == project_tmpl

    def test_returns_tuple(self):
        """Should return a tuple for hashability (LRU cache compatibility)."""
        from doxtr_doto.template_loader import get_template_dirs

        dirs = get_template_dirs()
        assert isinstance(dirs, tuple)


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_renders_bundled_doto_template(self):
        """Should render the bundled doto.html template."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "TASK-001",
                "title": "Test Task",
                "priority": "high",
                "status": "open",
                "assignee": "alice",
                "due": "2024-01-15",
                "tags": ["bug", "urgent"],
                "progress": 50,
                "is_overdue": False,
                "classes": "doto doto-priority-high",
            },
        )

        assert "TASK-001" in html
        assert "Test Task" in html
        assert "doto-priority-high" in html
        assert "alice" in html
        assert "bug" in html
        assert "urgent" in html
        assert "50%" in html

    def test_renders_table_template(self):
        """Should render the doto-list-table.html template."""
        from doxtr_doto.fields import COLUMN_LABELS
        from doxtr_doto.template_loader import render_template

        tasks = [
            MockTask(id="T-1", title="Task 1", priority="high"),
            MockTask(id="T-2", title="Task 2", priority="low"),
        ]

        html = render_template(
            "doto-list-table.html",
            {
                "tasks": tasks,
                "columns": ["id", "title", "priority"],
                "column_labels": COLUMN_LABELS,
            },
        )

        assert "<table" in html
        assert "T-1" in html
        assert "T-2" in html
        assert "Task 1" in html
        assert "Task 2" in html

    def test_renders_cards_template(self):
        """Should render the doto-list-cards.html template."""
        from doxtr_doto.template_loader import render_template

        tasks = [MockTask(id="T-1", title="Card Task")]

        html = render_template(
            "doto-list-cards.html",
            {
                "tasks": tasks,
            },
        )

        assert "doto-card" in html
        assert "T-1" in html
        assert "Card Task" in html

    def test_renders_simple_list_template(self):
        """Should render the doto-list-simple.html template."""
        from doxtr_doto.template_loader import render_template

        tasks = [MockTask(id="T-1", title="List Task")]

        html = render_template(
            "doto-list-simple.html",
            {
                "tasks": tasks,
            },
        )

        assert "<ul" in html
        assert "<li" in html
        assert "T-1" in html
        assert "List Task" in html

    def test_escapes_html_in_title(self):
        """Should escape HTML in user content (XSS prevention)."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "TASK-001",
                "title": "<script>alert('xss')</script>",
                "priority": "high",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": None,
                "is_overdue": False,
                "classes": "doto",
            },
        )

        # Script should be escaped
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "script" not in html.lower()

    def test_project_override_takes_priority(self, tmp_path):
        """Should use project template override when available."""
        from doxtr_doto.template_loader import clear_template_cache, render_template

        # Create project override
        project_tmpl = tmp_path / "_doto" / "templates" / "html"
        project_tmpl.mkdir(parents=True)

        # Write custom template
        custom_template = project_tmpl / "doto.html"
        custom_template.write_text('<div class="custom-override">{{ task_id }}</div>')

        # Clear cache to pick up new directory
        clear_template_cache()

        html = render_template(
            "doto.html",
            {
                "task_id": "TEST-ID",
                "title": "",
                "priority": "medium",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": None,
                "is_overdue": False,
                "classes": "doto",
            },
            srcdir=tmp_path,
        )

        assert "custom-override" in html
        assert "TEST-ID" in html

        # Clean up cache
        clear_template_cache()

    def test_handles_missing_template_gracefully(self):
        """Should return empty string for missing template without Jinja2 fallback."""
        from doxtr_doto.template_loader import render_template

        html = render_template("nonexistent-template.html", {})
        # Should return empty string (no fallback registered)
        assert html == ""

    def test_overdue_task_has_overdue_class(self):
        """Should add overdue class for overdue tasks."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "TASK-001",
                "title": "Overdue Task",
                "priority": "high",
                "status": "open",
                "assignee": "",
                "due": "2020-01-01",
                "tags": [],
                "progress": None,
                "is_overdue": True,
                "classes": "doto doto-priority-high doto-overdue",
            },
        )

        assert "doto-overdue" in html


class TestFallbackRenderers:
    """Tests for Python fallback renderers when Jinja2 is not available."""

    def test_fallback_render_doto(self):
        """Should render doto.html using Python fallback."""
        from doxtr_doto.template_loader import _fallback_render_doto

        html = _fallback_render_doto(
            {
                "task_id": "TASK-001",
                "title": "Fallback Test",
                "priority": "high",
                "status": "open",
                "assignee": "bob",
                "due": "2024-02-01",
                "tags": ["test"],
                "progress": 75,
                "is_overdue": False,
                "classes": "doto doto-priority-high",
            }
        )

        assert "TASK-001" in html
        assert "Fallback Test" in html
        assert "bob" in html
        assert "75%" in html
        assert "test" in html

    def test_fallback_render_table(self):
        """Should render table using Python fallback."""
        from doxtr_doto.fields import COLUMN_LABELS
        from doxtr_doto.template_loader import _fallback_render_table

        tasks = [MockTask(id="T-1", title="Table Task")]

        html = _fallback_render_table(
            {
                "tasks": tasks,
                "columns": ["id", "title"],
                "column_labels": COLUMN_LABELS,
            }
        )

        assert "<table" in html
        assert "T-1" in html
        assert "Table Task" in html

    def test_fallback_render_cards(self):
        """Should render cards using Python fallback."""
        from doxtr_doto.template_loader import _fallback_render_cards

        tasks = [MockTask(id="T-1", title="Card Task")]

        html = _fallback_render_cards(
            {
                "tasks": tasks,
            }
        )

        assert "doto-card" in html
        assert "T-1" in html

    def test_fallback_render_list(self):
        """Should render list using Python fallback."""
        from doxtr_doto.template_loader import _fallback_render_list

        tasks = [MockTask(id="T-1", title="List Task", assignee="alice")]

        html = _fallback_render_list(
            {
                "tasks": tasks,
            }
        )

        assert "<ul" in html
        assert "T-1" in html
        assert "@alice" in html

    def test_fallback_escapes_html(self):
        """Fallback renderers should escape HTML content."""
        from doxtr_doto.template_loader import _fallback_render_doto

        html = _fallback_render_doto(
            {
                "task_id": "TASK-001",
                "title": "<script>evil()</script>",
                "priority": "high",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": None,
                "is_overdue": False,
                "classes": "doto",
            }
        )

        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestJinjaFilters:
    """Tests for custom Jinja filters."""

    def test_escape_id_filter(self):
        """escape_id filter should sanitize HTML ids."""
        from doxtr_doto.template_loader import _escape_id_filter

        assert _escape_id_filter("TASK-001") == "TASK-001"
        assert _escape_id_filter("task<script>") == "task-script"
        assert _escape_id_filter("123-task") == "doto-123-task"

    def test_row_classes_filter(self):
        """row_classes filter should return CSS classes."""
        from doxtr_doto.template_loader import _row_classes_filter

        task = MockTask(priority="high", status="open")
        classes = _row_classes_filter(task)

        assert "doto-priority-high" in classes
        assert "doto-status-open" in classes

    def test_column_value_filter_id(self):
        """column_value filter should return task id."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(id="T-123")
        assert _column_value_filter(task, "id") == "T-123"

    def test_column_value_filter_title(self):
        """column_value filter should return task title."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(title="My Task")
        assert _column_value_filter(task, "title") == "My Task"

    def test_column_value_filter_tags(self):
        """column_value filter should return comma-separated tags."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(tags=["bug", "urgent"])
        assert _column_value_filter(task, "tags") == "bug, urgent"

    def test_column_value_filter_empty_assignee(self):
        """column_value filter should return empty string for no assignee."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(assignee=None)
        assert _column_value_filter(task, "assignee") == ""

    def test_column_value_filter_progress(self):
        """column_value filter should format progress with %."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(progress=50)
        assert _column_value_filter(task, "progress") == "50%"

        task_no_progress = MockTask(progress=None)
        assert _column_value_filter(task_no_progress, "progress") == ""

    def test_column_value_filter_estimate(self):
        """column_value filter should render estimate as a compact duration."""
        from doxtr_doto.template_loader import _column_value_filter

        task = MockTask(estimate=90)
        assert _column_value_filter(task, "estimate") == "1h30m"

        task_no_estimate = MockTask(estimate=None)
        assert _column_value_filter(task_no_estimate, "estimate") == ""


class TestTemplateExists:
    """Tests for template_exists function."""

    def test_bundled_template_exists(self):
        """Should return True for bundled templates."""
        from doxtr_doto.template_loader import template_exists

        assert template_exists("doto.html") is True
        assert template_exists("doto-list-table.html") is True

    def test_nonexistent_template(self):
        """Should return False for non-existent templates."""
        from doxtr_doto.template_loader import template_exists

        assert template_exists("nonexistent.html") is False

    def test_project_override_exists(self, tmp_path):
        """Should return True for project override templates."""
        from doxtr_doto.template_loader import template_exists

        project_tmpl = tmp_path / "_doto" / "templates" / "html"
        project_tmpl.mkdir(parents=True)
        (project_tmpl / "custom.html").write_text("<div>custom</div>")

        assert template_exists("custom.html", srcdir=tmp_path) is True


class TestClearTemplateCache:
    """Tests for clear_template_cache function."""

    def test_clear_cache_works(self):
        """Should clear the LRU cache without error."""
        from doxtr_doto.template_loader import clear_template_cache, render_template

        # Render to populate cache
        render_template(
            "doto.html",
            {
                "task_id": "T-1",
                "title": "",
                "priority": "medium",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": None,
                "is_overdue": False,
                "classes": "doto",
            },
        )

        # Should not raise
        clear_template_cache()


class TestFallbackWithJinja2Unavailable:
    """Tests for fallback behavior when Jinja2 is not installed."""

    def test_render_template_uses_fallback(self):
        """Should use Python fallback when Jinja2 unavailable."""
        from doxtr_doto import template_loader

        # Temporarily disable Jinja2
        original_available = template_loader.JINJA2_AVAILABLE
        template_loader.JINJA2_AVAILABLE = False

        try:
            html = template_loader.render_template(
                "doto.html",
                {
                    "task_id": "TASK-001",
                    "title": "Fallback Mode",
                    "priority": "high",
                    "status": "open",
                    "assignee": "",
                    "due": "",
                    "tags": [],
                    "progress": None,
                    "is_overdue": False,
                    "classes": "doto",
                },
            )

            assert "TASK-001" in html
            assert "Fallback Mode" in html
        finally:
            template_loader.JINJA2_AVAILABLE = original_available

    def test_missing_template_returns_empty(self):
        """Should return empty string for unregistered template in fallback mode."""
        from doxtr_doto import template_loader

        original_available = template_loader.JINJA2_AVAILABLE
        template_loader.JINJA2_AVAILABLE = False

        try:
            html = template_loader.render_template("unknown.html", {})
            assert html == ""
        finally:
            template_loader.JINJA2_AVAILABLE = original_available


class TestProgressRendering:
    """Tests for progress bar rendering."""

    def test_progress_bar_rendered_when_set(self):
        """Should render progress bar when progress is set."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "T-1",
                "title": "Task with progress",
                "priority": "medium",
                "status": "in-progress",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": 60,
                "is_overdue": False,
                "classes": "doto",
            },
        )

        assert "doto-progress" in html
        assert "60%" in html

    def test_progress_bar_not_rendered_when_none(self):
        """Should not render progress bar when progress is None."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "T-1",
                "title": "Task without progress",
                "priority": "medium",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": None,
                "is_overdue": False,
                "classes": "doto",
            },
        )

        assert "doto-progress-bar" not in html

    def test_progress_zero_is_rendered(self):
        """Should render progress bar even when progress is 0."""
        from doxtr_doto.template_loader import render_template

        html = render_template(
            "doto.html",
            {
                "task_id": "T-1",
                "title": "Task at 0%",
                "priority": "medium",
                "status": "open",
                "assignee": "",
                "due": "",
                "tags": [],
                "progress": 0,
                "is_overdue": False,
                "classes": "doto",
            },
        )

        assert "doto-progress" in html
        assert "0%" in html
