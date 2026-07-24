from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    BrandInvitationNotFoundError,
    BrandInvitationStateConflictError,
    BrandLastOwnerRequiredError,
    BrandNotFoundError,
    BrandOwnerRequiredError,
    InvitationUserNotFoundError,
)
from inspire_flow_backend.core.identity import nickname_key
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.brand import (
    BrandInvitation,
    BrandMembership,
    BrandOrganization,
)
from inspire_flow_backend.data.repositories import brands as brand_repository
from inspire_flow_backend.data.repositories import users as user_repository
from inspire_flow_backend.schemas.brands import (
    BrandCreate,
    BrandInvitationCreate,
    BrandInvitationPublic,
    BrandMembershipPublic,
    BrandMemberUpdate,
    BrandPage,
    BrandPublic,
    BrandUpdate,
)


@dataclass(frozen=True)
class BrandAccess:
    brand: BrandOrganization
    membership: BrandMembership


def require_brand_member(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
) -> BrandAccess:
    membership = brand_repository.get_membership(db, brand_id, user_id)
    brand = brand_repository.get_brand(db, brand_id)
    if membership is None or brand is None:
        raise BrandNotFoundError
    return BrandAccess(brand=brand, membership=membership)


def require_brand_owner(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
) -> BrandAccess:
    access = require_brand_member(db, brand_id, user_id)
    if access.membership.role != "owner":
        raise BrandOwnerRequiredError
    return access


def _brand_public(
    brand: BrandOrganization,
    membership: BrandMembership,
) -> BrandPublic:
    return BrandPublic(
        id=brand.id,
        name=brand.name,
        description=brand.description,
        website_url=brand.website_url,
        logo_url=brand.logo_url,
        my_role=membership.role,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


def _invitation_public(
    invitation: BrandInvitation,
    brand: BrandOrganization,
) -> BrandInvitationPublic:
    return BrandInvitationPublic(
        id=invitation.id,
        brand_id=invitation.brand_id,
        brand_name=brand.name,
        invited_user_id=invitation.invited_user_id,
        invited_by_user_id=invitation.invited_by_user_id,
        status=invitation.status,
        responded_at=invitation.responded_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


def create_brand(
    db: Session,
    user_id: UUID,
    payload: BrandCreate,
) -> BrandPublic:
    now = utc_now()
    brand = BrandOrganization(
        name=payload.name,
        description=payload.description,
        website_url=str(payload.website_url) if payload.website_url else None,
        logo_url=str(payload.logo_url) if payload.logo_url else None,
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    membership = BrandMembership(
        brand_id=brand.id,
        user_id=user_id,
        role="owner",
        created_at=now,
    )
    brand_repository.add_brand(db, brand)
    db.flush()
    membership.brand_id = brand.id
    brand_repository.add_membership(db, membership)
    db.commit()
    db.refresh(brand)
    db.refresh(membership)
    return _brand_public(brand, membership)


def list_brands(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> BrandPage:
    rows, total = brand_repository.list_user_brands(
        db,
        user_id,
        limit=limit,
        offset=offset,
    )
    return BrandPage(
        items=[_brand_public(brand, membership) for brand, membership in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def read_brand(db: Session, brand_id: UUID, user_id: UUID) -> BrandPublic:
    access = require_brand_member(db, brand_id, user_id)
    return _brand_public(access.brand, access.membership)


def update_brand(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
    payload: BrandUpdate,
) -> BrandPublic:
    access = require_brand_owner(db, brand_id, user_id)
    changed = False
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name in {"website_url", "logo_url"} and value is not None:
            value = str(value)
        if getattr(access.brand, field_name) != value:
            setattr(access.brand, field_name, value)
            changed = True
    if changed:
        access.brand.updated_at = utc_now()
        db.commit()
        db.refresh(access.brand)
    return _brand_public(access.brand, access.membership)


def create_invitation(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
    payload: BrandInvitationCreate,
) -> BrandInvitationPublic:
    access = require_brand_owner(db, brand_id, user_id)
    invited_user = user_repository.get_user_by_nickname_key(
        db,
        nickname_key(payload.nickname),
    )
    if invited_user is None:
        raise InvitationUserNotFoundError
    if brand_repository.get_membership(db, brand_id, invited_user.id) is not None:
        raise BrandInvitationStateConflictError
    existing = brand_repository.get_pending_invitation(
        db,
        brand_id,
        invited_user.id,
    )
    if existing is not None:
        return _invitation_public(existing, access.brand)

    now = utc_now()
    invitation = BrandInvitation(
        brand_id=brand_id,
        invited_user_id=invited_user.id,
        invited_by_user_id=user_id,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    brand_repository.add_invitation(db, invitation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = brand_repository.get_pending_invitation(
            db,
            brand_id,
            invited_user.id,
        )
        if existing is None:
            raise
        invitation = existing
    db.refresh(invitation)
    return _invitation_public(invitation, access.brand)


def list_invitations(
    db: Session,
    user_id: UUID,
) -> list[BrandInvitationPublic]:
    return [
        _invitation_public(invitation, brand)
        for invitation, brand in brand_repository.list_user_invitations(db, user_id)
    ]


def respond_to_invitation(
    db: Session,
    invitation_id: UUID,
    user_id: UUID,
    *,
    accept: bool,
) -> BrandInvitationPublic:
    invitation = brand_repository.get_invitation_for_user(
        db,
        invitation_id,
        user_id,
    )
    if invitation is None:
        raise BrandInvitationNotFoundError
    if invitation.status != "pending":
        raise BrandInvitationStateConflictError
    brand = brand_repository.get_brand(db, invitation.brand_id)
    if brand is None:
        raise BrandInvitationNotFoundError

    now = utc_now()
    invitation.status = "accepted" if accept else "declined"
    invitation.responded_at = now
    invitation.updated_at = now
    if accept and brand_repository.get_membership(db, brand.id, user_id) is None:
        brand_repository.add_membership(
            db,
            BrandMembership(
                brand_id=brand.id,
                user_id=user_id,
                role="member",
                created_at=now,
            ),
        )
    db.commit()
    db.refresh(invitation)
    return _invitation_public(invitation, brand)


def revoke_invitation(
    db: Session,
    brand_id: UUID,
    invitation_id: UUID,
    user_id: UUID,
) -> None:
    require_brand_owner(db, brand_id, user_id)
    invitation = brand_repository.get_brand_invitation(db, brand_id, invitation_id)
    if invitation is None:
        raise BrandInvitationNotFoundError
    if invitation.status != "pending":
        raise BrandInvitationStateConflictError
    now = utc_now()
    invitation.status = "revoked"
    invitation.responded_at = now
    invitation.updated_at = now
    db.commit()


def list_members(
    db: Session,
    brand_id: UUID,
    user_id: UUID,
) -> list[BrandMembershipPublic]:
    require_brand_member(db, brand_id, user_id)
    return [
        BrandMembershipPublic(
            user_id=membership.user_id,
            nickname=user.nickname,
            role=membership.role,
            created_at=membership.created_at,
        )
        for membership, user in brand_repository.list_brand_members(db, brand_id)
    ]


def update_member(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
    user_id: UUID,
    payload: BrandMemberUpdate,
) -> BrandMembershipPublic:
    require_brand_owner(db, brand_id, user_id)
    membership = brand_repository.get_membership(db, brand_id, member_user_id)
    member = user_repository.get_user_by_id(db, member_user_id)
    if membership is None or member is None:
        raise BrandNotFoundError
    if (
        membership.role == "owner"
        and payload.role == "member"
        and brand_repository.count_brand_owners(db, brand_id) <= 1
    ):
        raise BrandLastOwnerRequiredError
    if membership.role != payload.role:
        membership.role = payload.role
        db.commit()
        db.refresh(membership)
    return BrandMembershipPublic(
        user_id=membership.user_id,
        nickname=member.nickname,
        role=membership.role,
        created_at=membership.created_at,
    )


def remove_member(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
    user_id: UUID,
) -> None:
    require_brand_owner(db, brand_id, user_id)
    membership = brand_repository.get_membership(db, brand_id, member_user_id)
    if membership is None:
        raise BrandNotFoundError
    if membership.role == "owner" and brand_repository.count_brand_owners(db, brand_id) <= 1:
        raise BrandLastOwnerRequiredError
    brand_repository.delete_membership(db, membership)
    db.commit()
