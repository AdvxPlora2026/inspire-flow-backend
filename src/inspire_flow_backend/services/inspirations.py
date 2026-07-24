from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    ConversationNotFoundError,
    InspirationAssociationRequiredError,
    InspirationNotFoundError,
    ProjectNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.inspiration import Inspiration
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.repositories import (
    conversations as conversation_repository,
)
from inspire_flow_backend.data.repositories import (
    inspirations as inspiration_repository,
)
from inspire_flow_backend.data.repositories import messages as message_repository
from inspire_flow_backend.data.repositories import projects as project_repository
from inspire_flow_backend.schemas.inspirations import (
    InspirationCreate,
    InspirationPage,
    InspirationPublic,
    InspirationSortBy,
    InspirationSourceType,
    InspirationStatus,
    InspirationUpdate,
    SortOrder,
)


def create_inspiration(
    db: Session,
    user_id: UUID,
    payload: InspirationCreate,
    *,
    source_type: InspirationSourceType | None = None,
    source_conversation_id: UUID | None = None,
    source_message_id: UUID | None = None,
) -> Inspiration:
    projects = _get_owned_projects(db, user_id, payload.project_ids)
    _validate_source(
        db,
        user_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    resolved_source_type = source_type or InspirationSourceType(payload.source_type)
    _require_association(
        status=payload.status,
        projects=projects,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    now = utc_now()
    inspiration = Inspiration(
        user_id=user_id,
        title=payload.title,
        content=payload.content,
        status=payload.status.value,
        source_type=resolved_source_type.value,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        projects=projects,
        created_at=now,
        updated_at=now,
    )
    inspiration_repository.add_inspiration(db, inspiration)
    db.commit()
    db.refresh(inspiration)
    return inspiration


def get_inspiration(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
) -> Inspiration:
    inspiration = inspiration_repository.get_inspiration(
        db,
        user_id,
        inspiration_id,
    )
    if inspiration is None:
        raise InspirationNotFoundError
    return inspiration


def list_inspirations(
    db: Session,
    user_id: UUID,
    *,
    project_id: UUID | None = None,
    status: InspirationStatus | str | None = None,
    source_type: InspirationSourceType | str | None = None,
    query: str | None = None,
    sort_by: InspirationSortBy | str = InspirationSortBy.updated_at,
    sort_order: SortOrder | str = SortOrder.desc,
    limit: int,
    offset: int,
) -> InspirationPage:
    if project_id is not None and (project_repository.get_project(db, user_id, project_id) is None):
        raise ProjectNotFoundError
    normalized_query = query.strip() if query is not None else None
    if not normalized_query:
        normalized_query = None
    inspirations, total = inspiration_repository.list_inspirations(
        db,
        user_id,
        project_id=project_id,
        status=_enum_value(status),
        source_type=_enum_value(source_type),
        query=normalized_query,
        sort_by=_enum_value(sort_by) or InspirationSortBy.updated_at.value,
        sort_order=_enum_value(sort_order) or SortOrder.desc.value,
        limit=limit,
        offset=offset,
    )
    return InspirationPage(
        items=[to_public_inspiration(item) for item in inspirations],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_inspiration(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
    payload: InspirationUpdate,
) -> Inspiration:
    inspiration = get_inspiration(db, user_id, inspiration_id)
    target_projects = inspiration.projects
    if "project_ids" in payload.model_fields_set:
        target_projects = _get_owned_projects(
            db,
            user_id,
            payload.project_ids or [],
        )
    target_status = (
        payload.status
        if "status" in payload.model_fields_set
        else InspirationStatus(inspiration.status)
    )
    _require_association(
        status=target_status or InspirationStatus.inbox,
        projects=target_projects,
        source_conversation_id=inspiration.source_conversation_id,
        source_message_id=inspiration.source_message_id,
    )

    changed = False
    for field_name in ("title", "content", "status"):
        if field_name not in payload.model_fields_set:
            continue
        value = getattr(payload, field_name)
        if isinstance(value, InspirationStatus):
            value = value.value
        if getattr(inspiration, field_name) != value:
            setattr(inspiration, field_name, value)
            changed = True

    if "project_ids" in payload.model_fields_set:
        existing_ids = {project.id for project in inspiration.projects}
        target_ids = {project.id for project in target_projects}
        if existing_ids != target_ids:
            inspiration.projects = target_projects
            changed = True

    if not changed:
        return inspiration
    inspiration.updated_at = utc_now()
    db.commit()
    db.refresh(inspiration)
    return inspiration


def add_project_link(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
    project_id: UUID,
) -> None:
    inspiration = get_inspiration(db, user_id, inspiration_id)
    project = project_repository.get_project(db, user_id, project_id)
    if project is None:
        raise ProjectNotFoundError
    if any(linked.id == project.id for linked in inspiration.projects):
        return
    inspiration.projects.append(project)
    inspiration.updated_at = utc_now()
    db.commit()


def remove_project_link(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
    project_id: UUID,
) -> None:
    inspiration = get_inspiration(db, user_id, inspiration_id)
    project = project_repository.get_project(db, user_id, project_id)
    if project is None:
        raise ProjectNotFoundError
    linked = next(
        (item for item in inspiration.projects if item.id == project.id),
        None,
    )
    if linked is None:
        return
    remaining_projects = [item for item in inspiration.projects if item.id != project.id]
    _require_association(
        status=InspirationStatus(inspiration.status),
        projects=remaining_projects,
        source_conversation_id=inspiration.source_conversation_id,
        source_message_id=inspiration.source_message_id,
    )
    inspiration.projects.remove(linked)
    inspiration.updated_at = utc_now()
    db.commit()


def delete_inspiration(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
) -> None:
    inspiration = get_inspiration(db, user_id, inspiration_id)
    inspiration_repository.delete_inspiration(db, inspiration)
    db.commit()


def to_public_inspiration(inspiration: Inspiration) -> InspirationPublic:
    return InspirationPublic.model_validate(inspiration)


def project_orphan_candidates(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> list[Inspiration]:
    return inspiration_repository.list_project_orphan_candidates(
        db,
        user_id,
        project_id,
    )


def conversation_orphan_candidates(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> list[Inspiration]:
    return inspiration_repository.list_conversation_orphan_candidates(
        db,
        user_id,
        conversation_id,
    )


def orphan_impact_details(
    inspirations: list[Inspiration],
) -> list[dict[str, object]]:
    return [{"id": str(inspiration.id), "title": inspiration.title} for inspiration in inspirations]


def get_owned_inspirations(
    db: Session,
    user_id: UUID,
    inspiration_ids: list[UUID],
) -> list[Inspiration]:
    inspirations = inspiration_repository.get_owned_inspirations(
        db,
        user_id,
        inspiration_ids,
    )
    if {item.id for item in inspirations} != set(inspiration_ids):
        raise InspirationNotFoundError
    return inspirations


def _get_owned_projects(
    db: Session,
    user_id: UUID,
    project_ids: list[UUID],
) -> list[Project]:
    projects = inspiration_repository.get_owned_projects(
        db,
        user_id,
        project_ids,
    )
    if {project.id for project in projects} != set(project_ids):
        raise ProjectNotFoundError
    return projects


def _require_association(
    *,
    status: InspirationStatus,
    projects: list[Project],
    source_conversation_id: UUID | None,
    source_message_id: UUID | None,
) -> None:
    if (
        status != InspirationStatus.inbox
        and not projects
        and source_conversation_id is None
        and source_message_id is None
    ):
        raise InspirationAssociationRequiredError


def _validate_source(
    db: Session,
    user_id: UUID,
    *,
    source_conversation_id: UUID | None,
    source_message_id: UUID | None,
) -> None:
    if source_conversation_id is None and source_message_id is None:
        return
    if source_conversation_id is None or source_message_id is None:
        raise ConversationNotFoundError
    conversation = conversation_repository.get_conversation(
        db,
        user_id,
        source_conversation_id,
    )
    if conversation is None:
        raise ConversationNotFoundError
    message = message_repository.get_message(
        db,
        source_conversation_id,
        source_message_id,
    )
    if message is None:
        raise ConversationNotFoundError


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
