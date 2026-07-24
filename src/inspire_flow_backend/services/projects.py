from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import openai
from agents import AgentsException
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    AgentRunFailedError,
    ProjectNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.repositories import projects as project_repository
from inspire_flow_backend.schemas.projects import (
    ProjectCreate,
    ProjectDraft,
    ProjectPage,
    ProjectPublic,
    ProjectUpdate,
)

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
) -> Project:
    now = utc_now()
    project = Project(
        user_id=user_id,
        title=payload.title,
        type=payload.type,
        audience=payload.audience,
        summary=payload.summary,
        created_at=now,
        updated_at=now,
    )
    project_repository.add_project(db, project)
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
) -> None:
    project = get_project(db, user_id, project_id)
    project_repository.delete_project(db, project)
    db.commit()
