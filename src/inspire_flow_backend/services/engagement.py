from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    BrandInterestNotFoundError,
    BrandInterestStateConflictError,
    CreatorInboxItemNotFoundError,
    WorkshopNotPublishedError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.brand import (
    BrandFollow,
    BrandInterest,
    CreatorInboxItem,
)
from inspire_flow_backend.data.repositories import brands as brand_repository
from inspire_flow_backend.data.repositories import engagement as engagement_repository
from inspire_flow_backend.data.repositories import workshops as workshop_repository
from inspire_flow_backend.schemas.engagement import (
    BrandFollowPage,
    BrandFollowPublic,
    BrandInterestCreate,
    BrandInterestPage,
    BrandInterestPublic,
    CreatorInboxItemPublic,
    CreatorInboxItemUpdate,
    CreatorInboxMarkRead,
    CreatorInboxPage,
    CreatorInterestUpdate,
)
from inspire_flow_backend.services.brands import require_brand_member


@dataclass(frozen=True)
class InterestCreation:
    interest: BrandInterestPublic
    created: bool


def _require_published_creator(db: Session, creator_id: UUID) -> None:
    workshop = workshop_repository.get_workshop(db, creator_id)
    if workshop is None or workshop.status != "published" or workshop.published_revision_id is None:
        raise WorkshopNotPublishedError


def _follow_public(follow: BrandFollow) -> BrandFollowPublic:
    return BrandFollowPublic(
        id=follow.id,
        brand_id=follow.brand_id,
        creator_id=follow.creator_user_id,
        status=follow.status,
        followed_at=follow.followed_at,
        unfollowed_at=follow.unfollowed_at,
        created_at=follow.created_at,
        updated_at=follow.updated_at,
    )


def follow_creator(
    db: Session,
    brand_id: UUID,
    creator_id: UUID,
    member_user_id: UUID,
) -> BrandFollowPublic:
    require_brand_member(db, brand_id, member_user_id)
    _require_published_creator(db, creator_id)
    follow = engagement_repository.get_follow(db, brand_id, creator_id)
    now = utc_now()
    became_active = follow is None or follow.status != "active"
    if follow is None:
        follow = BrandFollow(
            brand_id=brand_id,
            creator_user_id=creator_id,
            status="active",
            followed_at=now,
            created_at=now,
            updated_at=now,
        )
        engagement_repository.add_follow(db, follow)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = engagement_repository.get_follow(db, brand_id, creator_id)
            if existing is None:
                raise
            return _follow_public(existing)
    elif became_active:
        follow.status = "active"
        follow.followed_at = now
        follow.unfollowed_at = None
        follow.updated_at = now

    if became_active:
        inbox = engagement_repository.get_inbox_item_by_reference(
            db,
            "follow",
            follow.id,
        )
        if inbox is None:
            inbox = CreatorInboxItem(
                creator_user_id=creator_id,
                brand_id=brand_id,
                kind="follow",
                reference_id=follow.id,
                is_read=False,
                event_at=now,
                created_at=now,
                updated_at=now,
            )
            engagement_repository.add_inbox_item(db, inbox)
        else:
            inbox.is_read = False
            inbox.read_at = None
            inbox.event_at = now
            inbox.updated_at = now
    db.commit()
    db.refresh(follow)
    return _follow_public(follow)


def unfollow_creator(
    db: Session,
    brand_id: UUID,
    creator_id: UUID,
    member_user_id: UUID,
) -> None:
    require_brand_member(db, brand_id, member_user_id)
    follow = engagement_repository.get_follow(db, brand_id, creator_id)
    if follow is None:
        return
    if follow.status == "active":
        now = utc_now()
        follow.status = "inactive"
        follow.unfollowed_at = now
        follow.updated_at = now
        db.commit()


def list_follows(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> BrandFollowPage:
    require_brand_member(db, brand_id, member_user_id)
    follows, total = engagement_repository.list_follows(
        db,
        brand_id,
        limit=limit,
        offset=offset,
    )
    return BrandFollowPage(
        items=[_follow_public(follow) for follow in follows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _interest_public(
    interest: BrandInterest,
    brand_name: str,
) -> BrandInterestPublic:
    return BrandInterestPublic(
        id=interest.id,
        brand_id=interest.brand_id,
        brand_name=brand_name,
        creator_id=interest.creator_user_id,
        message=interest.message,
        status=interest.status,
        created_by_user_id=interest.created_by_user_id,
        responded_at=interest.responded_at,
        created_at=interest.created_at,
        updated_at=interest.updated_at,
    )


def create_interest(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
    payload: BrandInterestCreate,
) -> InterestCreation:
    access = require_brand_member(db, brand_id, member_user_id)
    _require_published_creator(db, payload.creator_id)
    existing = engagement_repository.get_pending_interest(
        db,
        brand_id,
        payload.creator_id,
    )
    if existing is not None:
        return InterestCreation(
            interest=_interest_public(existing, access.brand.name),
            created=False,
        )

    now = utc_now()
    interest = BrandInterest(
        brand_id=brand_id,
        creator_user_id=payload.creator_id,
        message=payload.message,
        status="pending",
        created_by_user_id=member_user_id,
        created_at=now,
        updated_at=now,
    )
    engagement_repository.add_interest(db, interest)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = engagement_repository.get_pending_interest(
            db,
            brand_id,
            payload.creator_id,
        )
        if existing is None:
            raise
        return InterestCreation(
            interest=_interest_public(existing, access.brand.name),
            created=False,
        )
    engagement_repository.add_inbox_item(
        db,
        CreatorInboxItem(
            creator_user_id=payload.creator_id,
            brand_id=brand_id,
            kind="interest",
            reference_id=interest.id,
            is_read=False,
            event_at=now,
            created_at=now,
            updated_at=now,
        ),
    )
    db.commit()
    db.refresh(interest)
    return InterestCreation(
        interest=_interest_public(interest, access.brand.name),
        created=True,
    )


def list_interests(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> BrandInterestPage:
    access = require_brand_member(db, brand_id, member_user_id)
    interests, total = engagement_repository.list_interests(
        db,
        brand_id,
        limit=limit,
        offset=offset,
    )
    return BrandInterestPage(
        items=[_interest_public(interest, access.brand.name) for interest in interests],
        total=total,
        limit=limit,
        offset=offset,
    )


def withdraw_interest(
    db: Session,
    brand_id: UUID,
    interest_id: UUID,
    member_user_id: UUID,
) -> BrandInterestPublic:
    access = require_brand_member(db, brand_id, member_user_id)
    interest = engagement_repository.get_brand_interest(db, brand_id, interest_id)
    if interest is None:
        raise BrandInterestNotFoundError
    if interest.status != "pending":
        raise BrandInterestStateConflictError
    now = utc_now()
    interest.status = "withdrawn"
    interest.responded_at = now
    interest.updated_at = now
    db.commit()
    db.refresh(interest)
    return _interest_public(interest, access.brand.name)


def respond_to_interest(
    db: Session,
    creator_user_id: UUID,
    interest_id: UUID,
    payload: CreatorInterestUpdate,
) -> BrandInterestPublic:
    interest = engagement_repository.get_creator_interest(
        db,
        creator_user_id,
        interest_id,
    )
    if interest is None:
        raise BrandInterestNotFoundError
    if interest.status != "pending":
        raise BrandInterestStateConflictError
    brand = brand_repository.get_brand(db, interest.brand_id)
    if brand is None:
        raise BrandInterestNotFoundError
    now = utc_now()
    interest.status = payload.status.value
    interest.responded_at = now
    interest.updated_at = now
    db.commit()
    db.refresh(interest)
    return _interest_public(interest, brand.name)


def _inbox_public(
    db: Session,
    item: CreatorInboxItem,
    brand_name: str,
) -> CreatorInboxItemPublic:
    status = "unknown"
    message = None
    if item.kind == "follow":
        follow = engagement_repository.get_follow(
            db,
            item.brand_id,
            item.creator_user_id,
        )
        if follow is not None:
            status = follow.status
    elif item.kind == "interest":
        interest = engagement_repository.get_brand_interest(
            db,
            item.brand_id,
            item.reference_id,
        )
        if interest is not None:
            status = interest.status
            message = interest.message
    return CreatorInboxItemPublic(
        id=item.id,
        kind=item.kind,
        brand_id=item.brand_id,
        brand_name=brand_name,
        reference_id=item.reference_id,
        status=status,
        message=message,
        is_read=item.is_read,
        read_at=item.read_at,
        event_at=item.event_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def list_creator_inbox(
    db: Session,
    creator_user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> CreatorInboxPage:
    rows, total = engagement_repository.list_creator_inbox(
        db,
        creator_user_id,
        limit=limit,
        offset=offset,
    )
    return CreatorInboxPage(
        items=[_inbox_public(db, item, brand.name) for item, brand in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_inbox_item(
    db: Session,
    creator_user_id: UUID,
    item_id: UUID,
    payload: CreatorInboxItemUpdate,
) -> CreatorInboxItemPublic:
    item = engagement_repository.get_creator_inbox_item(
        db,
        creator_user_id,
        item_id,
    )
    if item is None:
        raise CreatorInboxItemNotFoundError
    if item.is_read != payload.is_read:
        now = utc_now()
        item.is_read = payload.is_read
        item.read_at = now if payload.is_read else None
        item.updated_at = now
        db.commit()
        db.refresh(item)
    brand = brand_repository.get_brand(db, item.brand_id)
    if brand is None:
        raise CreatorInboxItemNotFoundError
    return _inbox_public(db, item, brand.name)


def mark_inbox_read(
    db: Session,
    creator_user_id: UUID,
    payload: CreatorInboxMarkRead,
) -> CreatorInboxPage:
    items = engagement_repository.list_creator_inbox_for_update(
        db,
        creator_user_id,
        payload.item_ids,
    )
    now = utc_now()
    for item in items:
        if not item.is_read:
            item.is_read = True
            item.read_at = now
            item.updated_at = now
    db.commit()
    return list_creator_inbox(
        db,
        creator_user_id,
        limit=100,
        offset=0,
    )
