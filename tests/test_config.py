from importlib import import_module
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_settings_read_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Configured Service")
    monkeypatch.setenv("APP_VERSION", "test-git-sha")
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
        assert settings.version == "test-git-sha"
        assert settings.environment == "test"
        assert settings.debug is True
        assert settings.api_v1_prefix == "/custom/v1"
        assert settings.database_url == "sqlite:///./test.db"
        assert settings.session_ttl_hours == 12
    finally:
        config.get_settings.cache_clear()


def test_settings_version_defaults_to_dev(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        assert config.get_settings().version == "dev"
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


def test_stt_settings_have_isolated_bounded_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()

        assert settings.stt_enabled is False
        assert settings.stt_broker_url == "redis://127.0.0.1:6379/0"
        assert settings.stt_queue == "stt"
        assert settings.stt_spool_dir == Path(".inspireflow-stt-spool")
        assert settings.stt_api_key is None
        assert str(settings.stt_base_url) == ("https://ai.hackclub.com/proxy/v1/replicate")
        assert settings.stt_model == (
            "vaibhavs10/incredibly-fast-whisper:"
            "3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
        )
        assert settings.stt_request_timeout_seconds == 70
        assert settings.stt_prediction_timeout_seconds == 540
        assert settings.stt_poll_interval_seconds == 1.0
        assert settings.stt_max_upload_mib == 64
        assert settings.stt_max_duration_seconds == 300
        assert settings.stt_soft_time_limit_seconds == 600
        assert settings.stt_hard_time_limit_seconds == 660
        assert settings.stt_max_attempts == 3
        assert settings.stt_ready_ttl_seconds == 30
    finally:
        config.get_settings.cache_clear()


def test_blank_stt_api_key_is_treated_as_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("APP_STT_API_KEY", "  ")
    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        assert config.get_settings().stt_api_key is None
    finally:
        config.get_settings.cache_clear()


def test_stt_hard_limit_must_exceed_soft_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_STT_SOFT_TIME_LIMIT_SECONDS", "600")
    monkeypatch.setenv("APP_STT_HARD_TIME_LIMIT_SECONDS", "600")
    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(ValidationError):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_stt_prediction_timeout_must_be_below_soft_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_STT_PREDICTION_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("APP_STT_SOFT_TIME_LIMIT_SECONDS", "600")
    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(ValidationError):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_model_settings_load_provider_neutral_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("MODEL_BASE_URL", "https://model.example/v1")

    config = import_module("inspire_flow_backend.core.config")
    config.get_model_settings.cache_clear()

    try:
        settings = config.get_model_settings()

        assert settings.api_key is not None
        assert settings.api_key.get_secret_value() == "test-key"
        assert settings.name == "test-model"
        assert str(settings.base_url) == "https://model.example/v1"
    finally:
        config.get_model_settings.cache_clear()


def test_blank_optional_secret_settings_are_treated_as_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_CONTEXT_ENCRYPTION_KEY", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "")
    monkeypatch.setenv("MODEL_BASE_URL", "")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()
    config.get_model_settings.cache_clear()

    try:
        assert config.get_settings().context_encryption_key is None
        model = config.get_model_settings()
        assert model.api_key is None
        assert model.name is None
        assert model.base_url is None
    finally:
        config.get_settings.cache_clear()
        config.get_model_settings.cache_clear()


def test_legacy_deepseek_environment_names_do_not_configure_model(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "legacy-model")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "")
    monkeypatch.setenv("MODEL_BASE_URL", "")

    config = import_module("inspire_flow_backend.core.config")
    config.get_model_settings.cache_clear()

    try:
        model = config.get_model_settings()
        assert model.api_key is None
        assert model.name is None
        assert model.base_url is None
    finally:
        config.get_model_settings.cache_clear()
