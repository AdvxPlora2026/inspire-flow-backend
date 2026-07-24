from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    version: str = "dev"
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
    stt_enabled: bool = False
    stt_broker_url: str = "redis://127.0.0.1:6379/0"
    stt_queue: str = Field(default="stt", min_length=1)
    stt_spool_dir: Path = Path(".inspireflow-stt-spool")
    stt_model_cache_dir: Path = Path(".inspireflow-models")
    stt_model: str = Field(default="FunAudioLLM/SenseVoiceSmall", min_length=1)
    stt_model_hub: Literal["hf", "ms"] = "hf"
    stt_hf_disable_xet: bool = True
    stt_device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    stt_max_upload_mib: int = Field(default=64, gt=0)
    stt_max_duration_seconds: int = Field(default=300, gt=0)
    stt_soft_time_limit_seconds: int = Field(default=600, gt=0)
    stt_hard_time_limit_seconds: int = Field(default=660, gt=0)
    stt_max_attempts: int = Field(default=3, gt=0)
    stt_ready_ttl_seconds: int = Field(default=30, gt=0)
    injective_network: Literal["testnet", "mainnet"] = "testnet"
    injective_private_key: SecretStr | None = None
    injective_rpc_url: str | None = None
    injective_explorer_base_url: str | None = None
    injective_broadcast_denom: str = Field(default="inj", min_length=1)
    injective_broadcast_amount: str = Field(
        default="0.000000000000000001",
        min_length=1,
    )

    @field_validator(
        "context_encryption_key",
        "injective_private_key",
        "injective_rpc_url",
        "injective_explorer_base_url",
        mode="before",
    )
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
        if self.stt_hard_time_limit_seconds <= self.stt_soft_time_limit_seconds:
            raise ValueError("STT hard time limit must exceed the soft time limit")
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
