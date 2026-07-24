from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

TOTAL_SPLIT_BPS = 10_000

CommercialTaskStatus = Literal[
    "created",
    "escrow_funded",
    "submission_recorded",
    "authorization_activated",
    "settlement_released",
]
ChainTransactionStatus = Literal["prepared", "broadcast", "confirmed", "failed"]
ChainTransactionAction = Literal[
    "escrow_funded",
    "submission_recorded",
    "authorization_activated",
    "settlement_released",
]

ArtifactSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _normalize_amount(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    try:
        amount = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("Budget amount must be a decimal string") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Budget amount must be a positive decimal string")
    if -amount.as_tuple().exponent > 18:
        raise ValueError("Budget amount supports at most 18 decimal places")
    return normalized


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(min_length=1, max_length=40)
    denom: str = Field(min_length=1, max_length=16)

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value: object) -> object:
        return _normalize_amount(value)

    @field_validator("denom", mode="before")
    @classmethod
    def normalize_denom(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CommercialTaskSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: str = Field(min_length=1, max_length=100)
    bps: int = Field(ge=1, le=TOTAL_SPLIT_BPS)

    @field_validator("party_id", mode="before")
    @classmethod
    def normalize_party_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CommercialTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    title: str = Field(min_length=1, max_length=200)
    budget: Budget
    deadline: datetime
    splits: list[CommercialTaskSplit] = Field(min_length=1, max_length=16)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("Commercial task title cannot be blank")
            return normalized
        return value

    @field_validator("deadline")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Deadline must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_splits(self) -> Self:
        if sum(split.bps for split in self.splits) != TOTAL_SPLIT_BPS:
            raise ValueError(f"Split basis points must total exactly {TOTAL_SPLIT_BPS}")
        party_ids = [split.party_id for split in self.splits]
        if len(party_ids) != len(set(party_ids)):
            raise ValueError("Split party identifiers must be unique")
        return self


class CommercialTaskPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    user_id: UUID
    title: str
    budget: Budget
    deadline: datetime
    status: CommercialTaskStatus
    splits: list[CommercialTaskSplit]
    created_at: datetime
    updated_at: datetime


class CommercialSubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    artifact_sha256: ArtifactSha256
    delivery_url: Annotated[HttpUrl, Field(max_length=2048)]


class CommercialSubmissionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    task_id: UUID
    artifact_id: UUID
    artifact_sha256: str
    delivery_url: str
    created_at: datetime


class ChainTransactionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    action: ChainTransactionAction
    status: ChainTransactionStatus
    network: str
    chain_id: str | None
    transaction_hash: str | None
    explorer_url: str | None
    artifact_sha256: str | None
    amount: str | None
    denom: str | None
    failure_reason: str | None
    retryable: bool | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime


class CommercialTaskProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: CommercialTaskPublic
    submissions: list[CommercialSubmissionPublic]
    transactions: list[ChainTransactionPublic]
