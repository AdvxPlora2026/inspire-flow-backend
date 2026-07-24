from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import openai
from agents import AgentsException
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    AgentRunFailedError,
    OrphanedInspirationsConfirmationRequiredError,
    ProjectNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.repositories import projects as project_repository
from inspire_flow_backend.schemas.projects import (
    ProjectCreate,
    ProjectDetail,
    ProjectDraft,
    ProjectPage,
    ProjectPublic,
    ProjectUpdate,
)
from inspire_flow_backend.services import inspirations as inspiration_service

if TYPE_CHECKING:
    from inspire_flow_backend.services.agent.project_drafting import (
        ProjectDraftGenerator,
    )


async def draft_project(
    description: str,
    generator: ProjectDraftGenerator,
) -> ProjectDraft:
    try:
        return await generator.generate(description)
    except (AgentsException, openai.APIError, httpx.HTTPError) as exc:
        raise AgentRunFailedError from exc


def create_project(
    db: Session,
    user_id: UUID,
    payload: ProjectCreate,
    *,
    inspiration_ids: list[UUID] | None = None,
) -> Project:
    inspirations = inspiration_service.get_owned_inspirations(
        db,
        user_id,
        inspiration_ids or [],
    )
    now = utc_now()
    project = Project(
        user_id=user_id,
        title=payload.title,
        type=payload.type,
        audience=payload.audience,
        summary=payload.summary,
        icon_url=str(payload.icon_url) if payload.icon_url is not None else None,
        created_at=now,
        updated_at=now,
    )
    project_repository.add_project(db, project)
    for inspiration in inspirations:
        inspiration.projects.append(project)
        inspiration.updated_at = now
    db.commit()
    db.refresh(project)
    return project


def get_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> Project:
    project = project_repository.get_project(db, user_id, project_id)
    if project is None:
        raise ProjectNotFoundError
    return project


def get_project_detail(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> ProjectDetail:
    project = get_project(db, user_id, project_id)
    return ProjectDetail(
        **ProjectPublic.model_validate(project).model_dump(),
        inspiration_count=project_repository.count_project_inspirations(
            db,
            project.id,
        ),
    )


def list_projects(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> ProjectPage:
    projects, total = project_repository.list_projects(
        db,
        user_id,
        limit=limit,
        offset=offset,
    )
    return ProjectPage(
        items=[ProjectPublic.model_validate(project) for project in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    payload: ProjectUpdate,
) -> Project:
    project = get_project(db, user_id, project_id)
    changed = False
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "icon_url" and value is not None:
            value = str(value)
        if getattr(project, field_name) != value:
            setattr(project, field_name, value)
            changed = True

    if not changed:
        return project
    project.updated_at = utc_now()
    db.commit()
    db.refresh(project)
    return project


def delete_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    *,
    delete_orphan_inspirations: bool = False,
) -> None:
    project = get_project(db, user_id, project_id)
    orphan_candidates = inspiration_service.project_orphan_candidates(
        db,
        user_id,
        project_id,
    )
    if orphan_candidates and not delete_orphan_inspirations:
        raise OrphanedInspirationsConfirmationRequiredError(
            inspiration_service.orphan_impact_details(orphan_candidates)
        )
    for inspiration in orphan_candidates:
        db.delete(inspiration)
    project_repository.delete_project(db, project)
    db.commit()
