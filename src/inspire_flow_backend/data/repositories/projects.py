from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.inspiration import inspiration_projects
from inspire_flow_backend.data.models.project import Project


def add_project(db: Session, project: Project) -> None:
    db.add(project)


def get_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> Project | None:
    return db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )


def list_projects(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    owner_filter = Project.user_id == user_id
    total = db.scalar(select(func.count()).select_from(Project).where(owner_filter))
    projects = list(
        db.scalars(
            select(Project)
            .where(owner_filter)
            .order_by(Project.updated_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return projects, int(total or 0)


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)


def count_project_inspirations(
    db: Session,
    project_id: UUID,
) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(inspiration_projects)
        .where(inspiration_projects.c.project_id == project_id)
    )
    return int(count or 0)
