from functools import lru_cache
from pathlib import Path

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "Inspire Flow Backend"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./inspire_flow.db"
    session_ttl_hours: int = Field(default=24, gt=0)
    agent_context_trigger_characters: int = Field(default=24_000, gt=0)
    agent_context_max_characters: int = Field(default=48_000, gt=0)
    agent_context_recent_turns: int = Field(default=8, gt=0)
    agent_context_summary_max_characters: int = Field(default=6_000, gt=0)
    agent_memory_max_items: int = Field(default=30, gt=0, le=200)
    agent_memory_max_characters: int = Field(default=8_000, gt=0)
    agent_run_lock_ttl_seconds: int = Field(default=600, gt=0)
    context_encryption_key: SecretStr | None = None
    context_encryption_key_file: Path = Path(".inspireflow-context.key")

    @field_validator("context_encryption_key", mode="before")
    @classmethod
    def normalize_optional_context_key(cls, value: object) -> object:
        return _none_if_blank(value)

    @model_validator(mode="after")
    def validate_agent_context_budgets(self) -> "Settings":
        if self.agent_context_trigger_characters > self.agent_context_max_characters:
            raise ValueError("agent context trigger cannot exceed the hard context budget")
        reserved_context = (
            self.agent_context_summary_max_characters + self.agent_memory_max_characters
        )
        if reserved_context > self.agent_context_max_characters:
            raise ValueError("summary and memory budgets cannot exceed the hard context budget")
        return self


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MODEL_",
        extra="ignore",
    )

    api_key: SecretStr | None = None
    name: str | None = None
    base_url: AnyHttpUrl | None = None

    @field_validator("api_key", "name", "base_url", mode="before")
    @classmethod
    def normalize_optional_model_settings(cls, value: object) -> object:
        return _none_if_blank(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_model_settings() -> ModelSettings:
    return ModelSettings()


def _none_if_blank(value: object) -> object:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return value
