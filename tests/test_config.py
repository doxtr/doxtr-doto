"""Tests for doto configuration validation."""

from __future__ import annotations

import pytest


class TestValidateConfig:
    """Test the validate_config function."""

    def test_custom_statuses_allowed(self, doto_srcdir, make_app):
        """Test that validate_config allows custom statuses without warnings."""
        from doxtr_doto.config import validate_config

        # Configure with custom statuses - these should be allowed
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'review', 'testing', 'done']\n"
            "doto_default_status = 'open'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        # Custom statuses should not generate warnings
        status_warning = [w for w in warnings if "doto_statuses" in w and "unknown" in w]
        assert len(status_warning) == 0

    def test_custom_priorities_allowed(self, doto_srcdir, make_app):
        """Test that validate_config allows custom priorities without warnings."""
        from doxtr_doto.config import validate_config

        # Configure with custom priorities - these should be allowed
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_priorities = ['low', 'medium', 'high', 'urgent', 'super-high']\n"
            "doto_default_priority = 'medium'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        # Custom priorities should not generate warnings
        priority_warning = [w for w in warnings if "doto_priorities" in w and "unknown" in w]
        assert len(priority_warning) == 0

    def test_returns_warnings_for_invalid_default_status(self, doto_srcdir, make_app):
        """Test that validate_config returns warnings for invalid default status."""
        from doxtr_doto.config import validate_config

        # Configure with default status not in statuses list
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'in-progress', 'done']\n"
            "doto_default_status = 'pending'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        assert len(warnings) >= 1
        default_warning = [w for w in warnings if "doto_default_status" in w]
        assert len(default_warning) >= 1
        assert "pending" in default_warning[0]
        assert "not in doto_statuses" in default_warning[0]

    def test_returns_warnings_for_invalid_default_priority(self, doto_srcdir, make_app):
        """Test that validate_config returns warnings for invalid default priority."""
        from doxtr_doto.config import validate_config

        # Configure with default priority not in priorities list
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_priorities = ['low', 'medium', 'high', 'critical']\n"
            "doto_default_priority = 'urgent'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        assert len(warnings) >= 1
        default_warning = [w for w in warnings if "doto_default_priority" in w]
        assert len(default_warning) >= 1
        assert "urgent" in default_warning[0]
        assert "not in doto_priorities" in default_warning[0]

    def test_returns_warnings_for_invalid_conflict_action(self, doto_srcdir, make_app):
        """Test that validate_config returns warnings for invalid conflict_action."""
        from doxtr_doto.config import validate_config

        # Configure with invalid conflict action
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_conflict_action = 'ignore'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        assert len(warnings) >= 1
        conflict_warning = [w for w in warnings if "doto_conflict_action" in w]
        assert len(conflict_warning) >= 1
        assert "ignore" in conflict_warning[0]
        assert "must be one of" in conflict_warning[0]

    def test_returns_no_warnings_for_valid_config(self, doto_srcdir, make_app):
        """Test that validate_config returns no warnings for valid config."""
        from doxtr_doto.config import validate_config

        # Configure with all valid values
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'in-progress', 'blocked', 'done']\n"
            "doto_priorities = ['low', 'medium', 'high', 'critical']\n"
            "doto_default_status = 'open'\n"
            "doto_default_priority = 'medium'\n"
            "doto_conflict_action = 'error'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        assert len(warnings) == 0

    def test_returns_multiple_warnings_for_multiple_issues(self, doto_srcdir, make_app):
        """Test that validate_config returns multiple warnings when multiple issues."""
        from doxtr_doto.config import validate_config

        # Configure with multiple issues:
        # - default status not in statuses list
        # - default priority not in priorities list
        # - invalid conflict action
        # Note: custom statuses/priorities are now allowed, so we only test
        # that defaults must be in the configured sets
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'review']\n"
            "doto_priorities = ['low', 'high']\n"
            "doto_default_status = 'pending'\n"  # Not in statuses
            "doto_default_priority = 'urgent'\n"  # Not in priorities
            "doto_conflict_action = 'bad'\n"  # Invalid action
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)

        # Should have warnings for:
        # - default status not in statuses
        # - default priority not in priorities
        # - invalid conflict action
        assert len(warnings) >= 3


class TestGetConfig:
    """Test the get_config function."""

    def test_gets_config_value(self, doto_srcdir, make_app):
        """Test that get_config retrieves configuration values."""
        from doxtr_doto.config import get_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_default_status = 'in-progress'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        result = get_config(app, "default_status")
        assert result == "in-progress"

    def test_gets_config_value_with_prefix(self, doto_srcdir, make_app):
        """Test that get_config works with doto_ prefix."""
        from doxtr_doto.config import get_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_default_priority = 'high'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        result = get_config(app, "doto_default_priority")
        assert result == "high"

    def test_returns_default_for_missing_config(self, doto_srcdir, make_app):
        """Test that get_config returns default for missing config."""
        from doxtr_doto.config import get_config, DEFAULTS

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Use a config that's not overridden
        result = get_config(app, "enabled")
        assert result == DEFAULTS["doto_enabled"]


class TestSetupConfig:
    """Test the setup_config function."""

    def test_registers_all_config_values(self, doto_srcdir, make_app):
        """Test that setup_config registers all config values."""
        from doxtr_doto.config import DEFAULTS

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Check that all default config values are registered
        for name in DEFAULTS:
            assert hasattr(app.config, name), f"Config {name} not registered"

    def test_default_values_are_correct(self, doto_srcdir, make_app):
        """Test that default values are correctly applied."""
        from doxtr_doto.config import DEFAULTS

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Spot check some defaults
        assert app.config.doto_enabled == True
        assert app.config.doto_default_priority == "medium"
        assert app.config.doto_default_status == "open"
        assert app.config.doto_conflict_action == "error"
        assert app.config.doto_auto_archive == False


class TestConfigDefaults:
    """Test the DEFAULTS configuration dictionary."""

    def test_constants_match_defaults(self):
        """Test that DEFAULTS uses the constants correctly."""
        from doxtr_doto.constants import DEFAULT_PRIORITY, DEFAULT_STATUS
        from doxtr_doto.config import DEFAULTS
        
        assert DEFAULTS["doto_default_priority"] == DEFAULT_PRIORITY
        assert DEFAULTS["doto_default_status"] == DEFAULT_STATUS

    def test_defaults_contains_all_expected_keys(self):
        """Test that DEFAULTS contains all expected configuration keys."""
        from doxtr_doto.config import DEFAULTS

        expected_keys = [
            "doto_enabled",
            "doto_include_done",
            "doto_json_file",
            "doto_auto_archive",
            "doto_archive_doc",
            "doto_sync_on_build",
            "doto_conflict_action",
            "doto_default_priority",
            "doto_default_status",
            "doto_statuses",
            "doto_priorities",
            "doto_doxtr_integration",
        ]

        for key in expected_keys:
            assert key in DEFAULTS, f"Expected key {key} not in DEFAULTS"

    def test_default_statuses_are_valid(self):
        """Test that default statuses are valid."""
        from doxtr_doto.config import DEFAULTS

        statuses = DEFAULTS["doto_statuses"]
        assert "open" in statuses
        assert "in-progress" in statuses
        assert "blocked" in statuses
        assert "done" in statuses

    def test_default_priorities_are_valid(self):
        """Test that default priorities are valid."""
        from doxtr_doto.config import DEFAULTS

        priorities = DEFAULTS["doto_priorities"]
        assert "low" in priorities
        assert "medium" in priorities
        assert "high" in priorities
        assert "critical" in priorities

    def test_default_conflict_action_is_valid(self):
        """Test that default conflict_action is valid."""
        from doxtr_doto.config import DEFAULTS

        valid_actions = {"error", "warn", "prefer-rst", "prefer-json"}
        assert DEFAULTS["doto_conflict_action"] in valid_actions


class TestListIconModeConfig:
    """Test the doto_list_icon_mode option (Feature 5)."""

    def test_default_is_icon_text(self):
        from doxtr_doto.config import DEFAULTS

        assert DEFAULTS["doto_list_icon_mode"] == "icon-text"

    def test_registered_and_readable(self, doto_srcdir, make_app):
        from doxtr_doto.config import get_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_list_icon_mode = 'icon'\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        assert get_config(app, "list_icon_mode") == "icon"

    def test_valid_modes_no_warning(self, doto_srcdir, make_app):
        from doxtr_doto.config import validate_config

        for mode in ("icon", "icon-text", "text"):
            conf_py = doto_srcdir / "conf.py"
            conf_py.write_text(
                "extensions = ['doxtr_doto']\n"
                "master_doc = 'index'\n"
                f"doto_list_icon_mode = '{mode}'\n"
            )
            app = make_app(srcdir=doto_srcdir, buildername="html")
            warnings = validate_config(app)
            assert not [w for w in warnings if "doto_list_icon_mode" in w]

    def test_invalid_mode_warns(self, doto_srcdir, make_app):
        from doxtr_doto.config import validate_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_list_icon_mode = 'sparkles'\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)
        assert any("doto_list_icon_mode" in w for w in warnings)


class TestChartEngineConfig:
    """Test the doto_chart_engine option (Feature 7)."""

    def test_default_is_svg(self):
        from doxtr_doto.config import DEFAULTS

        assert DEFAULTS["doto_chart_engine"] == "svg"

    def test_registered_and_readable(self, doto_srcdir, make_app):
        from doxtr_doto.config import get_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_chart_engine = 'plotly'\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        assert get_config(app, "chart_engine") == "plotly"

    def test_valid_engines_no_warning(self, doto_srcdir, make_app):
        from doxtr_doto.config import validate_config

        for engine in ("svg", "plotly"):
            conf_py = doto_srcdir / "conf.py"
            conf_py.write_text(
                "extensions = ['doxtr_doto']\n"
                "master_doc = 'index'\n"
                f"doto_chart_engine = '{engine}'\n"
            )
            app = make_app(srcdir=doto_srcdir, buildername="html")
            warnings = validate_config(app)
            assert not [w for w in warnings if "doto_chart_engine" in w]

    def test_invalid_engine_warns(self, doto_srcdir, make_app):
        from doxtr_doto.config import validate_config

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_chart_engine = 'matplotlib'\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        warnings = validate_config(app)
        assert any("doto_chart_engine" in w for w in warnings)


class TestDotoListIcons:
    """Test the doto_list_icons config value (default + merge over defaults)."""

    def test_default_is_empty_dict(self):
        """doto_list_icons defaults to an empty dict (defaults untouched)."""
        from doxtr_doto.config import DEFAULTS

        assert DEFAULTS["doto_list_icons"] == {}

    def test_registered_and_default_applied(self, doto_srcdir, make_app):
        """The config value is registered with its empty-dict default."""
        from doxtr_doto.config import get_config

        app = make_app(srcdir=doto_srcdir, buildername="html")
        assert get_config(app, "list_icons") == {}

    def test_resolve_defaults_without_config(self):
        """_resolve_list_icons returns the built-in maps when app is None."""
        from doxtr_doto import nodes

        icons = nodes._resolve_list_icons(None)
        # Built-in field/value defaults survive.
        assert icons["fields"]["assignee"][0] == "fa-solid fa-user"
        assert icons["fields"]["assignee"][1] == r"\faUser"
        assert icons["status"]["done"][0] == "fa-solid fa-circle-check"
        assert icons["priority"]["critical"][1] == r"\faAnglesUp"

    def test_resolve_merges_custom_status_over_defaults(self, doto_srcdir, make_app):
        """A custom status icon merges in while defaults keep working."""
        from doxtr_doto import nodes

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'in-progress', 'blocked', 'done', 'deferred']\n"
            "doto_list_icons = {\n"
            "    'status': {'deferred': {'html': 'fa-solid fa-pause', 'latex': r'\\faPause'}},\n"
            "    'fields': {'due': 'fa-solid fa-clock'},\n"
            "}\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        icons = nodes._resolve_list_icons(app)

        # Custom status icon is present.
        assert icons["status"]["deferred"] == ("fa-solid fa-pause", r"\faPause")
        # A bare-string override becomes (html, None).
        assert icons["fields"]["due"] == ("fa-solid fa-clock", None)
        # Built-in defaults untouched.
        assert icons["status"]["done"][0] == "fa-solid fa-circle-check"
        assert icons["priority"]["low"][0] == "fa-solid fa-angle-down"

    def test_list_icon_html_uses_merged_map(self, doto_srcdir, make_app):
        """_list_icon_html honors config-merged custom status icons."""
        from doxtr_doto import nodes

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_statuses = ['open', 'in-progress', 'blocked', 'done', 'deferred']\n"
            "doto_list_icons = {\n"
            "    'status': {'deferred': {'html': 'fa-solid fa-pause', 'latex': r'\\faPause'}},\n"
            "}\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="html")
        icons = nodes._resolve_list_icons(app)

        assert nodes._list_icon_html("status", "deferred", icons) == "fa-solid fa-pause"
        assert nodes._list_icon_latex("status", "deferred", icons) == r"\faPause"
        # A status with no override still falls back to its default.
        assert nodes._list_icon_html("status", "done", icons) == "fa-solid fa-circle-check"
