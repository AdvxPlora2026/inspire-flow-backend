from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.inspiration import Inspiration
from inspire_flow_backend.data.models.project import Project


def add_inspiration(db: Session, inspiration: Inspiration) -> None:
    db.add(inspiration)


def get_inspiration(
    db: Session,
    user_id: UUID,
    inspiration_id: UUID,
) -> Inspiration | None:
    return db.scalar(
        select(Inspiration)
        .options(selectinload(Inspiration.projects))
        .where(
            Inspiration.id == inspiration_id,
            Inspiration.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )


def get_owned_projects(
    db: Session,
    user_id: UUID,
    project_ids: list[UUID],
) -> list[Project]:
    if not project_ids:
        return []
    return list(
        db.scalars(
            select(Project)
            .where(
                Project.user_id == user_id,
                Project.id.in_(project_ids),
            )
            .order_by(Project.id)
        )
    )


def get_owned_inspirations(
    db: Session,
    user_id: UUID,
    inspiration_ids: list[UUID],
) -> list[Inspiration]:
    if not inspiration_ids:
        return []
    return list(
        db.scalars(
            select(Inspiration)
            .options(selectinload(Inspiration.projects))
            .where(
                Inspiration.user_id == user_id,
                Inspiration.id.in_(inspiration_ids),
            )
            .order_by(Inspiration.id)
        )
    )


def list_inspirations(
    db: Session,
    user_id: UUID,
    *,
    project_id: UUID | None,
    status: str | None,
    source_type: str | None,
    query: str | None,
    sort_by: str,
    sort_order: str,
    limit: int,
    offset: int,
) -> tuple[list[Inspiration], int]:
    filters = [Inspiration.user_id == user_id]
    if project_id is not None:
        filters.append(Inspiration.projects.any(Project.id == project_id))
    if status is not None:
        filters.append(Inspiration.status == status)
    if source_type is not None:
        filters.append(Inspiration.source_type == source_type)
    if query is not None:
        filters.append(
            or_(
                Inspiration.title.contains(query, autoescape=True),
                Inspiration.content.contains(query, autoescape=True),
            )
        )

    total = db.scalar(select(func.count()).select_from(Inspiration).where(*filters))
    sort_column = Inspiration.created_at if sort_by == "created_at" else Inspiration.updated_at
    order_by = (
        (sort_column.asc(), Inspiration.id.asc())
        if sort_order == "asc"
        else (sort_column.desc(), Inspiration.id.desc())
    )
    inspirations = list(
        db.scalars(
            select(Inspiration)
            .options(selectinload(Inspiration.projects))
            .where(*filters)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
    )
    return inspirations, int(total or 0)


def delete_inspiration(db: Session, inspiration: Inspiration) -> None:
    db.delete(inspiration)


def list_project_orphan_candidates(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> list[Inspiration]:
    return list(
        db.scalars(
            select(Inspiration)
            .options(selectinload(Inspiration.projects))
            .where(
                Inspiration.user_id == user_id,
                Inspiration.projects.any(Project.id == project_id),
                ~Inspiration.projects.any(Project.id != project_id),
                Inspiration.source_conversation_id.is_(None),
                Inspiration.source_message_id.is_(None),
            )
            .order_by(Inspiration.updated_at.desc(), Inspiration.id.desc())
        )
    )


def list_conversation_orphan_candidates(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> list[Inspiration]:
    return list(
        db.scalars(
            select(Inspiration)
            .options(selectinload(Inspiration.projects))
            .where(
                Inspiration.user_id == user_id,
                or_(
                    Inspiration.source_conversation_id == conversation_id,
                    Inspiration.source_message.has(AgentMessage.conversation_id == conversation_id),
                ),
                ~Inspiration.projects.any(),
            )
            .order_by(Inspiration.updated_at.desc(), Inspiration.id.desc())
        )
    )
