from uuid import UUID

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ResourceImpactDetail(BaseModel):
    id: UUID
    title: str | None


class ResourceImpactErrorBody(BaseModel):
    code: str
    message: str
    details: list[ResourceImpactDetail]


class ResourceImpactErrorResponse(BaseModel):
    error: ResourceImpactErrorBody
