from importlib import import_module


def test_settings_read_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Configured Service")
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_API_V1_PREFIX", "/custom/v1")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()

        assert settings.name == "Configured Service"
        assert settings.environment == "test"
        assert settings.debug is True
        assert settings.api_v1_prefix == "/custom/v1"
    finally:
        config.get_settings.cache_clear()
