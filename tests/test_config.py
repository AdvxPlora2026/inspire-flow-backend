from importlib import import_module
from pathlib import Path

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


def test_agent_memory_settings_have_bounded_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()

        assert settings.agent_context_trigger_characters == 24_000
        assert settings.agent_context_max_characters == 48_000
        assert settings.agent_context_recent_turns == 8
        assert settings.agent_context_summary_max_characters == 6_000
        assert settings.agent_memory_max_items == 30
        assert settings.agent_memory_max_characters == 8_000
        assert settings.agent_run_lock_ttl_seconds == 600
        assert settings.context_encryption_key is None
        assert settings.context_encryption_key_file == Path(".inspireflow-context.key")
    finally:
        config.get_settings.cache_clear()


def test_agent_context_component_budgets_must_fit_hard_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_AGENT_CONTEXT_MAX_CHARACTERS", "1000")
    monkeypatch.setenv("APP_AGENT_CONTEXT_SUMMARY_MAX_CHARACTERS", "700")
    monkeypatch.setenv("APP_AGENT_MEMORY_MAX_CHARACTERS", "400")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(ValidationError):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_agent_context_trigger_must_not_exceed_hard_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_AGENT_CONTEXT_TRIGGER_CHARACTERS", "2000")
    monkeypatch.setenv("APP_AGENT_CONTEXT_MAX_CHARACTERS", "1000")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(ValidationError):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_deepseek_settings_load_existing_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://model.example/v1")

    config = import_module("inspire_flow_backend.core.config")
    config.get_deepseek_settings.cache_clear()

    try:
        settings = config.get_deepseek_settings()

        assert settings.api_key is not None
        assert settings.api_key.get_secret_value() == "test-key"
        assert settings.model == "test-model"
        assert str(settings.base_url) == "https://model.example/v1"
    finally:
        config.get_deepseek_settings.cache_clear()


def test_blank_optional_secret_settings_are_treated_as_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_CONTEXT_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_MODEL", "")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()
    config.get_deepseek_settings.cache_clear()

    try:
        assert config.get_settings().context_encryption_key is None
        deepseek = config.get_deepseek_settings()
        assert deepseek.api_key is None
        assert deepseek.model is None
        assert deepseek.base_url is None
    finally:
        config.get_settings.cache_clear()
        config.get_deepseek_settings.cache_clear()
