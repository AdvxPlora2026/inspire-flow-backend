from importlib import import_module

import pytest
from pydantic import ValidationError


def test_settings_read_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Configured Service")
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_API_V1_PREFIX", "/custom/v1")
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("APP_SESSION_TTL_HOURS", "12")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()

        assert settings.name == "Configured Service"
        assert settings.environment == "test"
        assert settings.debug is True
        assert settings.api_v1_prefix == "/custom/v1"
        assert settings.database_url == "sqlite:///./test.db"
        assert settings.session_ttl_hours == 12
    finally:
        config.get_settings.cache_clear()


def test_session_ttl_must_be_positive(monkeypatch):
    monkeypatch.setenv("APP_SESSION_TTL_HOURS", "0")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(ValidationError):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
