"""Tests for doxtr integration functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestDetectDoxtrFeatures:
    """Test the detect_doxtr_features function."""

    def test_returns_correct_dict_when_doxtr_not_loaded(self, doto_srcdir, make_app):
        """Test that detect_doxtr_features returns correct dict when doxtr not loaded."""
        from doxtr_doto.integration import detect_doxtr_features

        app = make_app(srcdir=doto_srcdir, buildername="html")

        result = detect_doxtr_features(app)

        assert isinstance(result, dict)
        assert "pdf_backend" in result
        assert "theme_config" in result
        assert "cross_references" in result
        # doxtr-pdf-theme-core should not be loaded
        assert result["pdf_backend"] is False
        assert result["cross_references"] is False

    def test_detects_doxtr_when_loaded(self, doto_srcdir, make_app):
        """Test that detect_doxtr_features detects doxtr when loaded."""
        from doxtr_doto.integration import detect_doxtr_features

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Mock doxtr extension being loaded
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_theme_defaults = {}

        result = detect_doxtr_features(app)

        assert result["pdf_backend"] is True
        assert result["theme_config"] is True
        # cross_references is always False (not implemented in doxtr-pdf-theme-core)
        assert result["cross_references"] is False

    def test_detects_theme_config_separately(self, doto_srcdir, make_app):
        """Test that theme_config detection is separate from pdf_backend."""
        from doxtr_doto.integration import detect_doxtr_features

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Mock extension loaded but no theme config
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()

        result = detect_doxtr_features(app)

        assert result["pdf_backend"] is True
        assert result["theme_config"] is False


class TestSetupDoxtrIntegration:
    """Test the setup_doxtr_integration function."""

    def test_handles_disabled_mode(self, doto_srcdir, make_app):
        """Test that setup_doxtr_integration handles disabled mode."""
        from doxtr_doto.integration import setup_doxtr_integration

        # Configure with integration disabled
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_doxtr_integration = 'disabled'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Should not raise and should not register containers
        setup_doxtr_integration(app)

        # No containers should be registered
        assert not hasattr(app.config, "doxtr_containers") or app.config.doxtr_containers == {}

    def test_auto_mode_without_doxtr(self, doto_srcdir, make_app):
        """Test auto mode doesn't register containers when doxtr not loaded."""
        from doxtr_doto.integration import setup_doxtr_integration

        # Configure with auto integration (default)
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\ndoto_doxtr_integration = 'auto'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        setup_doxtr_integration(app)

        # No doxtr_containers should be created or modified
        # since doxtr is not loaded

    def test_auto_mode_with_doxtr(self, doto_srcdir, make_app):
        """Test auto mode registers containers when doxtr is loaded."""
        from doxtr_doto.integration import setup_doxtr_integration

        # Configure with auto integration
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\ndoto_doxtr_integration = 'auto'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Mock doxtr being loaded
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_containers = {}

        setup_doxtr_integration(app)

        # Containers should be registered
        assert "doto-task" in app.config.doxtr_containers

    def test_enabled_mode_warns_when_doxtr_not_loaded(self, doto_srcdir, make_app):
        """Test enabled mode warns when doxtr is not loaded."""
        from doxtr_doto.integration import setup_doxtr_integration

        # Configure with integration enabled
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_doxtr_integration = 'enabled'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Capture warnings
        with patch("sphinx.util.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            setup_doxtr_integration(app)

            # Should have logged a warning
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "doxtr-pdf-theme-core" in warning_msg
            assert "not loaded" in warning_msg

    def test_enabled_mode_registers_containers_when_doxtr_loaded(self, doto_srcdir, make_app):
        """Test enabled mode registers containers when doxtr is loaded."""
        from doxtr_doto.integration import setup_doxtr_integration

        # Configure with integration enabled
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_doxtr_integration = 'enabled'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Mock doxtr being loaded
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_containers = {}

        setup_doxtr_integration(app)

        # Containers should be registered
        assert "doto-task" in app.config.doxtr_containers


class TestRegisterDoxtrContainers:
    """Test the _register_doxtr_containers function."""

    def test_adds_container_styles(self, doto_srcdir, make_app):
        """Test that _register_doxtr_containers adds container styles."""
        from doxtr_doto.integration import _register_doxtr_containers

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Set up doxtr_containers config
        app.config.doxtr_containers = {}

        _register_doxtr_containers(app)

        containers = app.config.doxtr_containers

        # Check base task container
        assert "doto-task" in containers
        assert "title_style" in containers["doto-task"]
        assert "title_color" in containers["doto-task"]

        # Check priority-specific containers
        assert "doto-task-low" in containers
        assert "doto-task-medium" in containers
        assert "doto-task-high" in containers
        assert "doto-task-critical" in containers

        # Verify colors
        assert containers["doto-task-low"]["title_color"] == "#6c757d"
        assert containers["doto-task-high"]["title_color"] == "#fd7e14"
        assert containers["doto-task-critical"]["title_color"] == "#dc3545"

    def test_does_not_override_existing_containers(self, doto_srcdir, make_app):
        """Test that _register_doxtr_containers doesn't override existing containers."""
        from doxtr_doto.integration import _register_doxtr_containers

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Set up existing container config
        app.config.doxtr_containers = {
            "doto-task": {"title_color": "#custom_color"},
        }

        _register_doxtr_containers(app)

        # Existing container should not be overwritten
        assert app.config.doxtr_containers["doto-task"]["title_color"] == "#custom_color"

        # Other containers should be added
        assert "doto-task-low" in app.config.doxtr_containers

    def test_does_nothing_without_doxtr_containers_config(self, doto_srcdir, make_app):
        """Test that _register_doxtr_containers does nothing without config."""
        from doxtr_doto.integration import _register_doxtr_containers

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Don't set up doxtr_containers config
        if hasattr(app.config, "doxtr_containers"):
            delattr(app.config, "doxtr_containers")

        # Should not raise
        _register_doxtr_containers(app)


class TestGetDoxtrColor:
    """Test the get_doxtr_color function."""

    def test_returns_color_from_palette(self, doto_srcdir, make_app):
        """Test that get_doxtr_color returns color from doxtr palette."""
        from doxtr_doto.integration import get_doxtr_color

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Set up semantic palette
        app.config.doxtr_semantic_palette = {
            "primary": "#007bff",
            "danger": "#dc3545",
        }

        result = get_doxtr_color(app, "primary")
        assert result == "#007bff"

        result = get_doxtr_color(app, "danger")
        assert result == "#dc3545"

    def test_returns_fallback_when_color_not_in_palette(self, doto_srcdir, make_app):
        """Test that get_doxtr_color returns fallback when color not found."""
        from doxtr_doto.integration import get_doxtr_color

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Set up semantic palette without the requested color
        app.config.doxtr_semantic_palette = {
            "primary": "#007bff",
        }

        result = get_doxtr_color(app, "nonexistent", fallback="#ffffff")
        assert result == "#ffffff"

    def test_returns_fallback_when_no_palette(self, doto_srcdir, make_app):
        """Test that get_doxtr_color returns fallback when no palette exists."""
        from doxtr_doto.integration import get_doxtr_color

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # No semantic palette
        if hasattr(app.config, "doxtr_semantic_palette"):
            delattr(app.config, "doxtr_semantic_palette")

        result = get_doxtr_color(app, "primary", fallback="#default")
        assert result == "#default"

    def test_default_fallback_is_black(self, doto_srcdir, make_app):
        """Test that default fallback color is black."""
        from doxtr_doto.integration import get_doxtr_color

        app = make_app(srcdir=doto_srcdir, buildername="html")

        result = get_doxtr_color(app, "nonexistent")
        assert result == "#000000"
