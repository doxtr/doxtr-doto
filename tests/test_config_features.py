"""Tests for config-driven validation features (Section 05)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sphinx_build(tmp_path):
    """Helper fixture that runs a minimal Sphinx HTML build."""

    def _build(
        rst_content: str, conf_extra: str = "", expect_warning: str | None = None
    ) -> tuple[Path, str, list[str]]:
        """
        Build a single RST page and return (outdir, page_html, warnings).

        Args:
            rst_content: The body of index.rst.
            conf_extra:  Extra lines appended to conf.py.
            expect_warning: If set, expect this warning substring in output.
        """
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        out = tmp_path / "out"

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\n" + conf_extra + "\n"
        )
        (src / "index.rst").write_text("Test\n====\n\n" + rst_content)

        import io

        from sphinx.application import Sphinx

        # Capture warnings
        warning_stream = io.StringIO()

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
            warning=warning_stream,
        )
        app.build()

        html = (out / "index.html").read_text() if (out / "index.html").exists() else ""
        warnings = warning_stream.getvalue().splitlines()

        return out, html, warnings

    return _build


@pytest.fixture
def sphinx_build_error(tmp_path):
    """Helper fixture that expects a Sphinx build to fail."""

    def _build(rst_content: str, conf_extra: str = "") -> str:
        """
        Build a single RST page and return error message.

        Args:
            rst_content: The body of index.rst.
            conf_extra:  Extra lines appended to conf.py.

        Returns:
            Error message string.
        """
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        out = tmp_path / "out"

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\n" + conf_extra + "\n"
        )
        (src / "index.rst").write_text("Test\n====\n\n" + rst_content)

        import io

        from sphinx.application import Sphinx

        warning_stream = io.StringIO()

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
            warning=warning_stream,
        )

        try:
            app.build()
        except Exception as e:
            return str(e)

        # If no exception, return warnings
        return warning_stream.getvalue()

    return _build


# ── Custom statuses/priorities tests ───────────────────────────────────────


def test_custom_status_accepted_in_doto_list(sphinx_build):
    """Custom doto_statuses = ['open', 'review', 'done'] accepted by doto-list."""
    _, html, warnings = sphinx_build(
        ".. doto:: Review task\n"
        "   :id: TASK-001\n"
        "   :status: review\n\n"
        ".. doto-list::\n"
        "   :status: review\n",
        conf_extra='doto_statuses = ["open", "review", "done"]',
    )
    # Should not have errors about invalid status
    error_warnings = [w for w in warnings if "Invalid status" in w]
    assert len(error_warnings) == 0
    assert "TASK-001" in html


def test_custom_priority_accepted_in_doto_list(sphinx_build):
    """Custom doto_priorities accepted by doto-list."""
    _, html, warnings = sphinx_build(
        ".. doto:: Urgent task\n"
        "   :id: TASK-002\n"
        "   :priority: urgent\n\n"
        ".. doto-list::\n"
        "   :priority: urgent\n",
        conf_extra='doto_priorities = ["low", "medium", "high", "urgent"]',
    )
    error_warnings = [w for w in warnings if "Invalid priority" in w]
    assert len(error_warnings) == 0
    assert "TASK-002" in html


def test_custom_status_accepted_in_doto_directive(sphinx_build):
    """Custom status value accepted in the doto directive itself."""
    _, html, warnings = sphinx_build(
        ".. doto:: Testing custom status\n   :id: TASK-003\n   :status: testing\n",
        conf_extra='doto_statuses = ["open", "testing", "done"]',
    )
    error_warnings = [w for w in warnings if "Invalid status" in w]
    assert len(error_warnings) == 0
    assert "TASK-003" in html


def test_invalid_status_rejected(sphinx_build_error):
    """Invalid status not in config is rejected."""
    result = sphinx_build_error(
        ".. doto:: Task with bad status\n   :id: TASK-004\n   :status: nonexistent\n",
    )
    assert "Invalid status" in result or "nonexistent" in result


def test_custom_status_in_doto_summary(sphinx_build):
    """Custom status accepted in doto-summary filter."""
    _, html, warnings = sphinx_build(
        ".. doto:: QA task\n"
        "   :id: TASK-005\n"
        "   :status: qa\n\n"
        ".. doto-summary::\n"
        "   :status: qa\n",
        conf_extra='doto_statuses = ["open", "qa", "done"]',
    )
    error_warnings = [w for w in warnings if "Invalid status" in w]
    assert len(error_warnings) == 0


# ── Required fields tests ──────────────────────────────────────────────────


def test_required_fields_missing_raises_error(sphinx_build_error):
    """doto_required_fields = ['assignee'] raises error when missing."""
    result = sphinx_build_error(
        ".. doto:: Task without assignee\n   :id: TASK-010\n",
        conf_extra='doto_required_fields = ["assignee"]',
    )
    assert "missing required field" in result.lower() or "assignee" in result.lower()


def test_required_fields_present_succeeds(sphinx_build):
    """Task with required field present builds successfully."""
    _, html, warnings = sphinx_build(
        ".. doto:: Task with assignee\n   :id: TASK-011\n   :assignee: alice\n",
        conf_extra='doto_required_fields = ["assignee"]',
    )
    # Should not have "missing required field" errors
    error_warnings = [w for w in warnings if "missing required" in w.lower()]
    assert len(error_warnings) == 0
    assert "TASK-011" in html


def test_multiple_required_fields(sphinx_build_error):
    """Multiple required fields all enforced."""
    result = sphinx_build_error(
        ".. doto:: Incomplete task\n   :id: TASK-012\n   :assignee: bob\n",
        conf_extra='doto_required_fields = ["assignee", "due"]',
    )
    # Should complain about missing 'due'
    assert "due" in result.lower() or "missing required" in result.lower()


def test_empty_required_fields_no_validation(sphinx_build):
    """Empty doto_required_fields means no validation."""
    _, html, _ = sphinx_build(
        ".. doto:: Minimal task\n   :id: TASK-013\n",
        conf_extra="doto_required_fields = []",
    )
    assert "TASK-013" in html


# ── Warn overdue tests ─────────────────────────────────────────────────────


def test_warn_overdue_emits_warning(sphinx_build):
    """doto_warn_overdue = True emits warning for overdue tasks."""
    _, html, warnings = sphinx_build(
        ".. doto:: Overdue task\n   :id: TASK-020\n   :due: 2000-01-01\n   :status: open\n",
        conf_extra="doto_warn_overdue = True",
    )
    # Should have an overdue warning
    overdue_warnings = [w for w in warnings if "overdue" in w.lower()]
    assert len(overdue_warnings) > 0
    assert "TASK-020" in html


def test_warn_overdue_false_no_warning(sphinx_build):
    """doto_warn_overdue = False does not emit overdue warnings."""
    _, html, warnings = sphinx_build(
        ".. doto:: Overdue but silent\n   :id: TASK-021\n   :due: 2000-01-01\n   :status: open\n",
        conf_extra="doto_warn_overdue = False",
    )
    # Should NOT have overdue warnings
    overdue_warnings = [w for w in warnings if "overdue" in w.lower()]
    assert len(overdue_warnings) == 0


def test_warn_overdue_skips_done_tasks(sphinx_build):
    """Done tasks are not reported as overdue."""
    _, html, warnings = sphinx_build(
        ".. doto:: Done overdue task\n   :id: TASK-022\n   :due: 2000-01-01\n   :status: done\n",
        conf_extra="doto_warn_overdue = True",
    )
    # Should NOT warn about done tasks even if overdue
    task_overdue_warnings = [w for w in warnings if "TASK-022" in w and "overdue" in w.lower()]
    assert len(task_overdue_warnings) == 0


def test_warn_overdue_skips_future_tasks(sphinx_build):
    """Future due dates don't trigger warnings."""
    _, html, warnings = sphinx_build(
        ".. doto:: Future task\n   :id: TASK-023\n   :due: 2099-12-31\n   :status: open\n",
        conf_extra="doto_warn_overdue = True",
    )
    # Should NOT have warning for future task
    task_overdue_warnings = [w for w in warnings if "TASK-023" in w and "overdue" in w.lower()]
    assert len(task_overdue_warnings) == 0


# ── validate_config tests ──────────────────────────────────────────────────


def test_validate_config_allows_custom_statuses():
    """validate_config does not warn about custom status values."""
    from doxtr_doto.config import validate_config

    class MockConfig:
        doto_statuses = ["open", "review", "testing", "done"]
        doto_priorities = ["low", "medium", "high", "critical"]
        doto_default_status = "open"
        doto_default_priority = "medium"
        doto_conflict_action = "error"

    class MockApp:
        config = MockConfig()

    warnings = validate_config(MockApp())
    # Should not warn about custom statuses
    status_warnings = [w for w in warnings if "unknown values" in w.lower()]
    assert len(status_warnings) == 0


def test_validate_config_warns_invalid_default():
    """validate_config warns when default is not in configured set."""
    from doxtr_doto.config import validate_config

    class MockConfig:
        doto_statuses = ["open", "done"]
        doto_priorities = ["low", "high"]
        doto_default_status = "nonexistent"  # Not in statuses
        doto_default_priority = "medium"  # Not in priorities
        doto_conflict_action = "error"

    class MockApp:
        config = MockConfig()

    warnings = validate_config(MockApp())
    # Should warn about invalid defaults
    assert any("default_status" in w.lower() for w in warnings)
    assert any("default_priority" in w.lower() for w in warnings)


def test_constants_match_defaults():
    """Constants match the config defaults."""
    from doxtr_doto.config import DEFAULTS
    from doxtr_doto.constants import DEFAULT_PRIORITY, DEFAULT_STATUS

    assert DEFAULTS["doto_default_priority"] == DEFAULT_PRIORITY
    assert DEFAULTS["doto_default_status"] == DEFAULT_STATUS


# ── doto_list_visible_tasks tests ──────────────────────────────────────────


def test_visible_tasks_default_is_five():
    """The global default doto_list_visible_tasks is 5."""
    from doxtr_doto.config import DEFAULTS

    assert DEFAULTS["doto_list_visible_tasks"] == 5


def test_validate_config_accepts_valid_visible_tasks():
    """validate_config does not warn for an int >= 0 visible-task cap."""
    from doxtr_doto.config import validate_config

    class MockConfig:
        doto_statuses = ["open", "done"]
        doto_priorities = ["low", "high"]
        doto_default_status = "open"
        doto_default_priority = "low"
        doto_conflict_action = "error"
        doto_list_visible_tasks = 0  # 0 = show all, still valid

    class MockApp:
        config = MockConfig()

    warnings = validate_config(MockApp())
    assert not any("visible_tasks" in w for w in warnings)


def test_validate_config_warns_invalid_visible_tasks():
    """validate_config warns when the visible-task cap is negative/non-int."""
    from doxtr_doto.config import validate_config

    class MockConfig:
        doto_statuses = ["open", "done"]
        doto_priorities = ["low", "high"]
        doto_default_status = "open"
        doto_default_priority = "low"
        doto_conflict_action = "error"
        doto_list_visible_tasks = -1  # invalid

    class MockApp:
        config = MockConfig()

    warnings = validate_config(MockApp())
    assert any("visible_tasks" in w for w in warnings)
