"""Round-trip and serialization tests for a due value with an optional time.

Covers the "due with time" foundation end-to-end at the data layer (no Sphinx
build needed): RST directive generation + re-parse, and JSON serialization via
:class:`DotoTask`. Rendering and directive-parsing are covered in
``tests/test_directive_doto.py``; low-level parsing in ``test_date_utils.py``.

Also covers the list-view HTML render seams (kanban / cards / email) and the
CLI overdue helpers, which must route a time-bearing due through the centralized
``date_utils`` formatter instead of leaking the raw ISO ``T`` form.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from doxtr_doto.collectors import DotoTask
from doxtr_doto.sync.rst_writer import _parse_rst_for_directives, generate_directive_text


@dataclass
class _RenderTask:
    """Minimal task object for exercising the fallback list renderers."""

    id: str = "T-1"
    title: str = "Timed Task"
    priority: str = "high"
    status: str = "open"
    assignee: str | None = "alice"
    due: str | None = "2026-08-15T16:00"
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    body: str = ""
    _is_overdue: bool = False

    def is_overdue(self) -> bool:
        return self._is_overdue


@pytest.mark.parametrize(
    "due",
    [
        "2026-08-15",
        "2026-08-15T16:00",
        "2026-08-15T16:00:31",
    ],
)
def test_rst_roundtrip_preserves_due(due):
    """generate_directive_text -> parse re-reads the exact stored due string."""
    rst = generate_directive_text({"id": "T1", "title": "Task", "due": due})
    assert f":due: {due}" in rst

    parsed = _parse_rst_for_directives(rst)
    assert len(parsed) == 1
    assert parsed[0]["options"]["due"] == due


@pytest.mark.parametrize(
    "due",
    [
        "2026-08-15",
        "2026-08-15T16:00",
        "2026-08-15T16:00:31",
    ],
)
def test_json_roundtrip_preserves_due(due):
    """DotoTask.to_dict/from_dict round-trips the due losslessly (incl. time).

    __post_init__ normalizes the due; it must not drop the time component.
    """
    task = DotoTask(id="T1", title="Task", due=due)
    # __post_init__ normalization keeps the time.
    assert task.due == due

    data = task.to_dict()
    assert data["due"] == due

    restored = DotoTask.from_dict("T1", data)
    assert restored.due == due


def test_old_date_only_json_still_loads():
    """A legacy date-only JSON payload loads unchanged (non-breaking)."""
    task = DotoTask.from_dict("LEGACY-1", {"title": "Old", "due": "2026-08-15"})
    assert task.due == "2026-08-15"


def test_sync_dict_preserves_time():
    """to_sync_dict carries the full time-bearing due for sync write-back."""
    task = DotoTask(id="T1", title="Task", due="2026-08-15T16:00")
    assert task.to_sync_dict()["due"] == "2026-08-15T16:00"


def test_due_date_property_returns_calendar_day():
    """due_date returns the calendar date for a time-bearing due."""
    from datetime import date

    task = DotoTask(id="T1", title="Task", due="2026-08-15T16:00")
    assert task.due_date == date(2026, 8, 15)


def test_dototask_is_overdue_false_when_done_with_past_time():
    """A done task is never overdue, even with a past time-bearing due."""
    task = DotoTask(id="T1", title="Task", due="2000-01-01T16:00", status="done")
    assert task.is_overdue() is False


# --- List-view render seams: time must be formatted, not leaked as ISO 'T' ---


def test_cards_fallback_formats_timed_due():
    """The cards fallback renders a timed due as 'HH:MM', not the ISO 'T' form."""
    from doxtr_doto.template_loader import _fallback_render_cards

    html = _fallback_render_cards({"tasks": [_RenderTask()]})
    assert "2026-08-15 16:00" in html
    assert "2026-08-15T16:00" not in html


def test_kanban_fallback_formats_timed_due():
    """The kanban fallback renders a timed due as 'HH:MM', not the ISO 'T' form."""
    from doxtr_doto.template_loader import _fallback_render_kanban

    html = _fallback_render_kanban(
        {
            "columns": [("open", "Open")],
            "grouped": {"open": [_RenderTask()]},
        }
    )
    assert "2026-08-15 16:00" in html
    assert "2026-08-15T16:00" not in html


def test_email_fallback_formats_timed_due():
    """The email fallback renders a timed due as 'HH:MM', not the ISO 'T' form."""
    from doxtr_doto.template_loader import _fallback_render_email

    html = _fallback_render_email(
        {
            "columns": [("open", "Open")],
            "tree": {"open": [_RenderTask()]},
            "tasks": [_RenderTask()],
        }
    )
    assert "2026-08-15 16:00" in html
    assert "2026-08-15T16:00" not in html


@pytest.mark.parametrize(
    "renderer",
    ["doto-list-cards.html", "doto-list-kanban.html", "doto-list-email.html"],
)
def test_jinja_list_templates_format_timed_due(renderer):
    """The Jinja list templates route a timed due through the display seam."""
    from doxtr_doto.template_loader import render_template

    ctx = {
        "tasks": [_RenderTask()],
        "columns": [("open", "Open")],
        "grouped": {"open": [_RenderTask()]},
        "tree": {"open": [_RenderTask()]},
    }
    html = render_template(renderer, ctx)
    assert "2026-08-15 16:00" in html
    assert "2026-08-15T16:00" not in html


# --- CLI overdue helpers must tolerate / honor a time-bearing due ---


def test_cli_is_task_overdue_handles_timed_due():
    """update._is_task_overdue tolerates the ISO 'T' form (was date.fromisoformat)."""
    from doxtr_doto.cli.commands.update import _is_task_overdue

    assert _is_task_overdue({"due": "2000-01-01T16:00", "status": "open"}) is True
    assert _is_task_overdue({"due": "2000-01-01T16:00", "status": "done"}) is False
    # A far-future timed due is not overdue.
    assert _is_task_overdue({"due": "2999-01-01T16:00", "status": "open"}) is False
