from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.brand import (
    BrandInvitation,
    BrandMembership,
    BrandOrganization,
)
from inspire_flow_backend.data.models.user import User


def add_brand(db: Session, brand: BrandOrganization) -> None:
    db.add(brand)


def add_membership(db: Session, membership: BrandMembership) -> None:
    db.add(membership)


def add_invitation(db: Session, invitation: BrandInvitation) -> None:
    db.add(invitation)


def delete_membership(db: Session, membership: BrandMembership) -> None:
    db.delete(membership)


def get_brand(db: Session, brand_id: UUID) -> BrandOrganization | None:
    return db.get(BrandOrganization, brand_id)


def get_membership(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
) -> BrandMembership | None:
    return db.scalar(
        select(BrandMembership).where(
            BrandMembership.brand_id == brand_id,
            BrandMembership.user_id == user_id,
        )
    )


def list_user_brands(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[BrandOrganization, BrandMembership]], int]:
    membership_filter = BrandMembership.user_id == user_id
    total = db.scalar(select(func.count()).select_from(BrandMembership).where(membership_filter))
    rows = list(
        db.execute(
            select(BrandOrganization, BrandMembership)
            .join(
                BrandMembership,
                BrandMembership.brand_id == BrandOrganization.id,
            )
            .where(membership_filter)
            .order_by(BrandOrganization.updated_at.desc(), BrandOrganization.id.desc())
            .limit(limit)
            .offset(offset)
        ).tuples()
    )
    return rows, int(total or 0)


def list_brand_members(
    db: Session,
    brand_id: UUID,
) -> list[tuple[BrandMembership, User]]:
    return list(
        db.execute(
            select(BrandMembership, User)
            .join(User, User.id == BrandMembership.user_id)
            .where(BrandMembership.brand_id == brand_id)
            .order_by(BrandMembership.created_at.asc(), BrandMembership.id.asc())
        ).tuples()
    )


def count_brand_owners(db: Session, brand_id: UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(BrandMembership)
        .where(
            BrandMembership.brand_id == brand_id,
            BrandMembership.role == "owner",
        )
    )
    return int(count or 0)


def get_pending_invitation(
    db: Session,
    brand_id: UUID,
    invited_user_id: UUID,
) -> BrandInvitation | None:
    return db.scalar(
        select(BrandInvitation).where(
            BrandInvitation.brand_id == brand_id,
            BrandInvitation.invited_user_id == invited_user_id,
            BrandInvitation.status == "pending",
        )
    )


def get_invitation_for_user(
    db: Session,
    invitation_id: UUID,
    invited_user_id: UUID,
) -> BrandInvitation | None:
    return db.scalar(
        select(BrandInvitation).where(
            BrandInvitation.id == invitation_id,
            BrandInvitation.invited_user_id == invited_user_id,
        )
    )


def get_brand_invitation(
    db: Session,
    brand_id: UUID,
    invitation_id: UUID,
) -> BrandInvitation | None:
    return db.scalar(
        select(BrandInvitation).where(
            BrandInvitation.id == invitation_id,
            BrandInvitation.brand_id == brand_id,
        )
    )


def list_user_invitations(
    db: Session,
    invited_user_id: UUID,
) -> list[tuple[BrandInvitation, BrandOrganization]]:
    return list(
        db.execute(
            select(BrandInvitation, BrandOrganization)
            .join(
                BrandOrganization,
                BrandOrganization.id == BrandInvitation.brand_id,
            )
            .where(BrandInvitation.invited_user_id == invited_user_id)
            .order_by(BrandInvitation.updated_at.desc(), BrandInvitation.id.desc())
        ).tuples()
    )
