"""Tests for the [calendar] config table and the provider factory."""

from __future__ import annotations

import pytest

from doxtr_doto.calsync.providers import get_provider
from doxtr_doto.cli.config import CalendarConfig, _apply_calendar_config


class TestCalendarConfig:
    def test_defaults(self):
        cc = CalendarConfig()
        assert cc.enabled is False
        assert cc.event_mode == "event"
        assert cc.direction == "push"
        assert cc.workday_start == "08:00"
        assert cc.workday_end == "17:00"
        assert cc.break_start == "12:00"
        assert cc.break_end == "13:00"
        assert cc.event_duration_minutes == 30
        assert cc.all_day_for_dateless is True

    def test_apply_toml_table(self):
        from doxtr_doto.cli.config import DotoConfig

        cfg = DotoConfig()
        _apply_calendar_config(
            cfg,
            {
                "enabled": True,
                "provider": "google",
                "calendar": "primary",
                "event_mode": "todo",
                "workday_start": "09:00",
                "workday_end": "18:00",
                "break_start": "12:30",
                "break_end": "13:30",
                "event_duration_minutes": 45,
                "all_day_for_dateless": False,
                "username": "me@example.com",
                "conflict_policy": "merge",
            },
        )
        cc = cfg.calendar
        assert cc.enabled is True
        assert cc.provider == "google"
        assert cc.event_mode == "todo"
        assert cc.workday_start == "09:00"
        assert cc.event_duration_minutes == 45
        assert cc.all_day_for_dateless is False
        assert cc.username == "me@example.com"
        assert cc.normalized_conflict_policy() == "merge"

    def test_apply_empty_table_noop(self):
        from doxtr_doto.cli.config import DotoConfig

        cfg = DotoConfig()
        _apply_calendar_config(cfg, {})
        assert cfg.calendar.provider == ""

    def test_unknown_keys_ignored(self):
        from doxtr_doto.cli.config import DotoConfig

        cfg = DotoConfig()
        _apply_calendar_config(cfg, {"future_option": "x", "provider": "caldav"})
        assert cfg.calendar.provider == "caldav"

    def test_password_env_resolution(self, monkeypatch):
        monkeypatch.setenv("MY_CAL_PW", "s3cret")
        cc = CalendarConfig(password="$MY_CAL_PW")
        assert cc.resolved_password() == "s3cret"

    def test_empty_password_resolves_empty(self):
        assert CalendarConfig().resolved_password() == ""


class TestProviderFactory:
    def test_known_providers(self):
        from doxtr_doto.calsync.providers.caldav import CalDAVProvider
        from doxtr_doto.calsync.providers.google import GoogleCalendarProvider
        from doxtr_doto.calsync.providers.microsoft import MicrosoftCalendarProvider

        assert get_provider("google") is GoogleCalendarProvider
        assert get_provider("microsoft") is MicrosoftCalendarProvider
        assert get_provider("outlook") is MicrosoftCalendarProvider
        assert get_provider("caldav") is CalDAVProvider
        assert get_provider("apple") is CalDAVProvider
        assert get_provider("icloud") is CalDAVProvider

    def test_case_insensitive(self):
        from doxtr_doto.calsync.providers.google import GoogleCalendarProvider

        assert get_provider("GOOGLE") is GoogleCalendarProvider

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown calendar provider"):
            get_provider("yahoo")


class TestProviderRegistry:
    def test_register_and_resolve_custom_provider(self):
        from doxtr_doto.calsync.providers import (
            get_provider,
            register_provider,
        )
        from doxtr_doto.calsync.providers.base import CalendarProvider

        class _Mine(CalendarProvider):
            name = "mine"

            def connect(self):
                pass

            def create_event(self, event):
                pass

            def update_event(self, event, *, etag="", href=""):
                pass

            def delete_event(self, uid, *, etag="", href=""):
                pass

        register_provider("mytestprovider", lambda: _Mine)
        assert get_provider("MyTestProvider") is _Mine

    def test_register_override_builtin(self):
        from doxtr_doto.calsync.providers import get_provider, register_provider
        from doxtr_doto.calsync.providers.caldav import CalDAVProvider

        sentinel = object()
        register_provider("override-demo", lambda: sentinel)
        assert get_provider("override-demo") is sentinel
        # Built-ins remain intact.
        assert get_provider("caldav") is CalDAVProvider


class TestCalendarConfigValidation:
    def test_valid_config_has_no_errors(self):
        cc = CalendarConfig(provider="google", event_mode="event", direction="push")
        assert cc.validate() == []

    def test_unknown_provider_error(self):
        cc = CalendarConfig(provider="yahoo")
        errors = cc.validate()
        assert any("Unknown calendar provider" in e for e in errors)

    def test_unknown_event_mode_error(self):
        cc = CalendarConfig(provider="google", event_mode="appointment")
        assert any("event_mode" in e for e in cc.validate())

    def test_unsupported_direction_error(self):
        cc = CalendarConfig(provider="google", direction="sideways")
        assert any("direction" in e for e in cc.validate())

    def test_two_way_direction_is_valid(self):
        for d in ("two-way", "twoway", "both", "TWO-WAY"):
            cc = CalendarConfig(provider="google", direction=d)
            assert cc.validate() == []
            assert cc.normalized_direction() == "two-way"

    def test_push_direction_normalizes(self):
        assert CalendarConfig(direction="push").normalized_direction() == "push"
        assert CalendarConfig().normalized_direction() == "push"

    def test_pull_direction_is_valid(self):
        for d in ("pull", "PULL", "  pull  "):
            cc = CalendarConfig(provider="google", direction=d)
            assert cc.validate() == []
            assert cc.normalized_direction() == "pull"

    def test_validate_matches_normalized_whitespace(self):
        # validate() and normalized_direction() must agree on surrounding
        # whitespace: a padded alias is valid and normalizes correctly.
        cc = CalendarConfig(provider="google", direction="  Two-Way  ")
        assert cc.validate() == []
        assert cc.normalized_direction() == "two-way"

    def test_aliases_are_valid(self):
        for p in ("apple", "icloud", "outlook", "ms", "graph", "caldav"):
            assert CalendarConfig(provider=p).validate() == []

    def test_default_conflict_policy_is_local_wins(self):
        assert CalendarConfig().normalized_conflict_policy() == "local-wins"

    def test_merge_conflict_policy_aliases_normalize(self):
        for p in ("merge", "three-way", "3-way", "MERGE", "  merge  "):
            cc = CalendarConfig(provider="google", conflict_policy=p)
            assert cc.validate() == []
            assert cc.normalized_conflict_policy() == "merge"

    def test_local_wins_conflict_policy_aliases_normalize(self):
        for p in ("local-wins", "localwins", "local", "LOCAL"):
            cc = CalendarConfig(provider="google", conflict_policy=p)
            assert cc.validate() == []
            assert cc.normalized_conflict_policy() == "local-wins"

    def test_unknown_conflict_policy_error(self):
        cc = CalendarConfig(provider="google", conflict_policy="newest")
        assert any("conflict_policy" in e for e in cc.validate())
