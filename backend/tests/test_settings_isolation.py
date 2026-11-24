"""Tests must behave the same locally and in CI: no value from a developer's .env (which
`docker compose run` copies into the environment) may reach the settings under test."""

import os

from app.core.config import Settings, get_settings
from tests.conftest import CONNECTION_VARS, TEST_OVERRIDES


def _default(name: str) -> object:
    field = Settings.model_fields[name]
    return field.default_factory() if field.default_factory is not None else field.default  # type: ignore[call-arg]


def test_every_setting_is_a_code_default_or_an_explicit_test_override() -> None:
    settings = get_settings()
    leaked = {
        name: getattr(settings, name)
        for name in Settings.model_fields
        if name.upper() not in CONNECTION_VARS | set(TEST_OVERRIDES)
        and getattr(settings, name) != _default(name)
    }
    assert leaked == {}, f"settings leaked from the environment (.env?): {sorted(leaked)}"


def test_no_settings_variable_is_left_in_the_environment() -> None:
    allowed = CONNECTION_VARS | set(TEST_OVERRIDES)
    stray = [
        name.upper()
        for name in Settings.model_fields
        if name.upper() not in allowed and (name.upper() in os.environ or name in os.environ)
    ]
    assert stray == []


def test_secrets_are_the_code_defaults_in_tests() -> None:
    settings = get_settings()
    assert settings.groq_api_key == "" and settings.gemini_api_key == ""
    assert settings.ingest_cron_enabled is True  # the default a .env once turned off


def test_tests_cannot_reach_the_internet() -> None:
    import socket

    import pytest

    with pytest.raises(OSError, match="may not reach the internet"):
        socket.getaddrinfo("himalayas.app", 443)
