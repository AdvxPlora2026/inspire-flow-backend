from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

AdvisoryUrl = Annotated[HttpUrl, Field(max_length=2048)]


def _normalize_required(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Field cannot be blank")
    return normalized


def _normalize_string_list(values: object) -> object:
    if not isinstance(values, list):
        return values
    normalized: list[object] = []
    seen: set[str] = set()
    for value in values:
        candidate = _normalize_required(value)
        if not isinstance(candidate, str):
            normalized.append(candidate)
            continue
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(candidate)
    return normalized


class EvidenceStatus(StrEnum):
    sufficient = "sufficient"
    limited = "limited"
    insufficient = "insufficient"


class EvidenceVerification(StrEnum):
    search_result = "search_result"
    fetched_page = "fetched_page"


class AdvisoryFreshness(StrEnum):
    in_window = "in_window"
    out_of_window = "out_of_window"
    unknown = "unknown"


class AdvisoryPriority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class AdvisoryConfidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class BrandAdvisoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_brief: str = Field(min_length=1, max_length=6000)
    project_id: UUID | None = None
    market: str = Field(default="China mainland", min_length=1, max_length=120)
    focus_topics: list[str] = Field(default_factory=list, max_length=5)
    lookback_days: int = Field(default=7, ge=1, le=30)

    @field_validator("project_brief", "market", mode="before")
    @classmethod
    def normalize_required_fields(cls, value: object) -> object:
        return _normalize_required(value)

    @field_validator("focus_topics", mode="before")
    @classmethod
    def normalize_focus_topics(cls, value: object) -> object:
        return _normalize_string_list(value)

    @field_validator("focus_topics")
    @classmethod
    def validate_focus_topic_lengths(cls, values: list[str]) -> list[str]:
        if any(len(value) > 100 for value in values):
            raise ValueError("Focus topics must be at most 100 characters")
        return values


class BrandAdvisoryBrand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    website_url: AdvisoryUrl | None = None


class LinkedProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    title: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=50)
    audience: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2000)


class BrandAdvisoryProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brief: str = Field(min_length=1, max_length=6000)
    linked_project: LinkedProjectContext | None = None


class BrandAdvisoryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brand: BrandAdvisoryBrand
    project: BrandAdvisoryProjectContext
    market: str = Field(min_length=1, max_length=120)
    focus_topics: list[str] = Field(default_factory=list, max_length=5)
    lookback_days: int = Field(ge=1, le=30)


class AdvisoryEvidenceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    url: AdvisoryUrl
    summary: str = Field(min_length=1, max_length=1200)
    project_relevance: str = Field(min_length=1, max_length=1200)

    @field_validator("id", "summary", "project_relevance", mode="before")
    @classmethod
    def normalize_fields(cls, value: object) -> object:
        return _normalize_required(value)


class AdvisoryReasoning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[str] = Field(min_length=1, max_length=8)
    implications: list[str] = Field(min_length=1, max_length=8)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("observations", "implications", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _normalize_string_list(value)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value: object) -> object:
        return _normalize_required(value)


class AdvisoryRecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: AdvisoryPriority
    time_window: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=2000)
    expected_effect: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    reasoning: AdvisoryReasoning
    risks: list[str] = Field(min_length=1, max_length=8)
    counterarguments: list[str] = Field(min_length=1, max_length=8)
    assumptions: list[str] = Field(min_length=1, max_length=8)
    confidence: AdvisoryConfidence

    @field_validator(
        "time_window",
        "action",
        "expected_effect",
        mode="before",
    )
    @classmethod
    def normalize_required_fields(cls, value: object) -> object:
        return _normalize_required(value)

    @field_validator(
        "evidence_ids",
        "risks",
        "counterarguments",
        "assumptions",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _normalize_string_list(value)


class BrandAdvisoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[AdvisoryEvidenceDraft] = Field(default_factory=list, max_length=20)
    recommendations: list[AdvisoryRecommendationDraft] = Field(default_factory=list, max_length=10)
    caveats: list[str] = Field(default_factory=list, max_length=10)
    next_research_steps: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("caveats", "next_research_steps", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _normalize_string_list(value)


class AdvisoryResearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: str
    focus_topics: list[str]
    lookback_days: int
    window_start: datetime
    window_end: datetime
    executed_queries: list[str]


class AdvisoryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: str
    source_domain: str
    summary: str
    project_relevance: str
    retrieved_at: datetime
    verification: EvidenceVerification
    freshness: AdvisoryFreshness
    published_at: datetime | None


class AdvisoryRecommendation(AdvisoryRecommendationDraft):
    pass


class BrandAdvisoryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    evidence_status: EvidenceStatus
    brand: BrandAdvisoryBrand
    project_context: BrandAdvisoryProjectContext
    research_scope: AdvisoryResearchScope
    evidence: list[AdvisoryEvidence]
    recommendations: list[AdvisoryRecommendation]
    caveats: list[str]
    next_research_steps: list[str]
