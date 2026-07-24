from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.brand import (
    BrandFollow,
    BrandInterest,
    BrandOrganization,
    CreatorInboxItem,
)


def add_follow(db: Session, follow: BrandFollow) -> None:
    db.add(follow)


def get_follow(
    db: Session,
    brand_id: UUID,
    creator_user_id: UUID,
) -> BrandFollow | None:
    return db.scalar(
        select(BrandFollow).where(
            BrandFollow.brand_id == brand_id,
            BrandFollow.creator_user_id == creator_user_id,
        )
    )


def list_follows(
    db: Session,
    brand_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[BrandFollow], int]:
    filters = (
        BrandFollow.brand_id == brand_id,
        BrandFollow.status == "active",
    )
    total = db.scalar(select(func.count()).select_from(BrandFollow).where(*filters))
    rows = list(
        db.scalars(
            select(BrandFollow)
            .where(*filters)
            .order_by(BrandFollow.updated_at.desc(), BrandFollow.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total or 0)


def add_interest(db: Session, interest: BrandInterest) -> None:
    db.add(interest)


def get_pending_interest(
    db: Session,
    brand_id: UUID,
    creator_user_id: UUID,
) -> BrandInterest | None:
    return db.scalar(
        select(BrandInterest).where(
            BrandInterest.brand_id == brand_id,
            BrandInterest.creator_user_id == creator_user_id,
            BrandInterest.status == "pending",
        )
    )


def get_brand_interest(
    db: Session,
    brand_id: UUID,
    interest_id: UUID,
) -> BrandInterest | None:
    return db.scalar(
        select(BrandInterest).where(
            BrandInterest.id == interest_id,
            BrandInterest.brand_id == brand_id,
        )
    )


def get_creator_interest(
    db: Session,
    creator_user_id: UUID,
    interest_id: UUID,
) -> BrandInterest | None:
    return db.scalar(
        select(BrandInterest).where(
            BrandInterest.id == interest_id,
            BrandInterest.creator_user_id == creator_user_id,
        )
    )


def list_interests(
    db: Session,
    brand_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[BrandInterest], int]:
    scope = BrandInterest.brand_id == brand_id
    total = db.scalar(select(func.count()).select_from(BrandInterest).where(scope))
    rows = list(
        db.scalars(
            select(BrandInterest)
            .where(scope)
            .order_by(BrandInterest.updated_at.desc(), BrandInterest.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total or 0)


def add_inbox_item(db: Session, item: CreatorInboxItem) -> None:
    db.add(item)


def get_inbox_item_by_reference(
    db: Session,
    kind: str,
    reference_id: UUID,
) -> CreatorInboxItem | None:
    return db.scalar(
        select(CreatorInboxItem).where(
            CreatorInboxItem.kind == kind,
            CreatorInboxItem.reference_id == reference_id,
        )
    )


def get_creator_inbox_item(
    db: Session,
    creator_user_id: UUID,
    item_id: UUID,
) -> CreatorInboxItem | None:
    return db.scalar(
        select(CreatorInboxItem).where(
            CreatorInboxItem.id == item_id,
            CreatorInboxItem.creator_user_id == creator_user_id,
        )
    )


def list_creator_inbox(
    db: Session,
    creator_user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[CreatorInboxItem, BrandOrganization]], int]:
    scope = CreatorInboxItem.creator_user_id == creator_user_id
    total = db.scalar(select(func.count()).select_from(CreatorInboxItem).where(scope))
    rows = list(
        db.execute(
            select(CreatorInboxItem, BrandOrganization)
            .join(
                BrandOrganization,
                BrandOrganization.id == CreatorInboxItem.brand_id,
            )
            .where(scope)
            .order_by(CreatorInboxItem.event_at.desc(), CreatorInboxItem.id.desc())
            .limit(limit)
            .offset(offset)
        ).tuples()
    )
    return rows, int(total or 0)


def list_creator_inbox_for_update(
    db: Session,
    creator_user_id: UUID,
    item_ids: list[UUID] | None,
) -> list[CreatorInboxItem]:
    filters = [CreatorInboxItem.creator_user_id == creator_user_id]
    if item_ids is not None:
        filters.append(CreatorInboxItem.id.in_(item_ids))
    return list(db.scalars(select(CreatorInboxItem).where(*filters)))
