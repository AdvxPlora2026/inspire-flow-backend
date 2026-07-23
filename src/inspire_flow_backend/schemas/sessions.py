from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from inspire_flow_backend.core.identity import clean_nickname
from inspire_flow_backend.schemas.users import UserPublic


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        return clean_nickname(value)


class SessionCreated(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserPublic
