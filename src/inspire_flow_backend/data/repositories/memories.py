from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.user_memory import UserMemory


def get_memory(
    db: Session,
    user_id: UUID,
    memory_id: UUID,
) -> UserMemory | None:
    return db.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user_id,
        )
    )


def get_memory_by_fingerprint(
    db: Session,
    user_id: UUID,
    fingerprint: str,
) -> UserMemory | None:
    return db.scalar(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.content_fingerprint == fingerprint,
        )
    )


def list_memories(
    db: Session,
    user_id: UUID,
    *,
    status: str | None,
    category: str | None,
    limit: int,
    offset: int,
) -> tuple[list[UserMemory], int]:
    filters = [UserMemory.user_id == user_id]
    if status is not None:
        filters.append(UserMemory.status == status)
    if category is not None:
        filters.append(UserMemory.category == category)

    total = db.scalar(select(func.count()).select_from(UserMemory).where(*filters))
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(*filters)
            .order_by(
                UserMemory.is_pinned.desc(),
                UserMemory.updated_at.desc(),
                UserMemory.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return memories, int(total or 0)


def list_active_memories_for_context(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
) -> list[UserMemory]:
    return list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
            )
            .order_by(
                UserMemory.is_pinned.desc(),
                UserMemory.updated_at.desc(),
                UserMemory.id.asc(),
            )
            .limit(limit)
        )
    )


def add_memory(db: Session, memory: UserMemory) -> None:
    db.add(memory)


def delete_memory(db: Session, memory: UserMemory) -> None:
    db.delete(memory)
