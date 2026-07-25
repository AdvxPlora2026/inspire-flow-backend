from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import openai
from agents import AgentsException
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import AgentRunFailedError
from inspire_flow_backend.schemas.advisory import (
    BrandAdvisoryBrand,
    BrandAdvisoryContext,
    BrandAdvisoryProjectContext,
    BrandAdvisoryReport,
    BrandAdvisoryRequest,
    LinkedProjectContext,
)
from inspire_flow_backend.services import brands as brand_service
from inspire_flow_backend.services import projects as project_service

if TYPE_CHECKING:
    from inspire_flow_backend.services.agent.brand_advisor import BrandAdvisor


async def analyze_brand_project(
    db: Session,
    user_id: UUID,
    brand_id: UUID,
    payload: BrandAdvisoryRequest,
    advisor: BrandAdvisor,
) -> BrandAdvisoryReport:
    try:
        access = brand_service.require_brand_member(db, brand_id, user_id)
        linked_project = None
        if payload.project_id is not None:
            project = project_service.get_project(db, user_id, payload.project_id)
            linked_project = LinkedProjectContext(
                id=project.id,
                title=project.title,
                type=project.type,
                audience=project.audience,
                summary=project.summary,
            )
        context = BrandAdvisoryContext(
            brand=BrandAdvisoryBrand(
                id=access.brand.id,
                name=access.brand.name,
                description=access.brand.description,
                website_url=access.brand.website_url,
            ),
            project=BrandAdvisoryProjectContext(
                brief=payload.project_brief,
                linked_project=linked_project,
            ),
            market=payload.market,
            focus_topics=list(payload.focus_topics),
            lookback_days=payload.lookback_days,
        )
    finally:
        if db.in_transaction():
            db.rollback()

    try:
        return await advisor.analyze(context)
    except (AgentsException, openai.APIError, httpx.HTTPError) as exc:
        raise AgentRunFailedError from exc
