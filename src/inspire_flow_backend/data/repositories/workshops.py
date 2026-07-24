from uuid import UUID

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.brand import BrandFollow
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.models.workshop import (
    CreatorWorkshop,
    WorkshopBrandAuthorization,
    WorkshopContact,
    WorkshopProjectSelection,
    WorkshopPublication,
    WorkshopPublicationContact,
    WorkshopPublicationProjectCard,
    WorkshopPublicationSocialAccount,
    WorkshopSocialAccount,
)


def add_workshop(db: Session, workshop: CreatorWorkshop) -> None:
    db.add(workshop)


def get_workshop(db: Session, user_id: UUID) -> CreatorWorkshop | None:
    return db.get(CreatorWorkshop, user_id)


def add_publication(db: Session, publication: WorkshopPublication) -> None:
    db.add(publication)


def add_social_account(db: Session, account: WorkshopSocialAccount) -> None:
    db.add(account)


def get_social_account(
    db: Session,
    workshop_user_id: UUID,
    account_id: UUID,
) -> WorkshopSocialAccount | None:
    return db.scalar(
        select(WorkshopSocialAccount).where(
            WorkshopSocialAccount.id == account_id,
            WorkshopSocialAccount.workshop_user_id == workshop_user_id,
        )
    )


def delete_social_account(db: Session, account: WorkshopSocialAccount) -> None:
    db.delete(account)


def add_contact(db: Session, contact: WorkshopContact) -> None:
    db.add(contact)


def get_contact(
    db: Session,
    workshop_user_id: UUID,
    contact_id: UUID,
) -> WorkshopContact | None:
    return db.scalar(
        select(WorkshopContact).where(
            WorkshopContact.id == contact_id,
            WorkshopContact.workshop_user_id == workshop_user_id,
        )
    )


def delete_contact(db: Session, contact: WorkshopContact) -> None:
    db.delete(contact)


def add_project_selection(
    db: Session,
    selection: WorkshopProjectSelection,
) -> None:
    db.add(selection)


def get_project_selection(
    db: Session,
    workshop_user_id: UUID,
    project_id: UUID,
) -> WorkshopProjectSelection | None:
    return db.scalar(
        select(WorkshopProjectSelection).where(
            WorkshopProjectSelection.workshop_user_id == workshop_user_id,
            WorkshopProjectSelection.project_id == project_id,
        )
    )


def delete_project_selection(
    db: Session,
    selection: WorkshopProjectSelection,
) -> None:
    db.delete(selection)


def add_publication_items(
    db: Session,
    items: list[
        WorkshopPublicationSocialAccount
        | WorkshopPublicationContact
        | WorkshopPublicationProjectCard
    ],
) -> None:
    db.add_all(items)


def get_publication(
    db: Session,
    publication_id: UUID,
) -> WorkshopPublication | None:
    return db.get(WorkshopPublication, publication_id)


def next_publication_version(db: Session, workshop_user_id: UUID) -> int:
    version = db.scalar(
        select(func.max(WorkshopPublication.version)).where(
            WorkshopPublication.workshop_user_id == workshop_user_id
        )
    )
    return int(version or 0) + 1


def list_social_accounts(
    db: Session,
    workshop_user_id: UUID,
) -> list[WorkshopSocialAccount]:
    return list(
        db.scalars(
            select(WorkshopSocialAccount)
            .where(WorkshopSocialAccount.workshop_user_id == workshop_user_id)
            .order_by(WorkshopSocialAccount.sort_order, WorkshopSocialAccount.id)
        )
    )


def list_contacts(db: Session, workshop_user_id: UUID) -> list[WorkshopContact]:
    return list(
        db.scalars(
            select(WorkshopContact)
            .where(WorkshopContact.workshop_user_id == workshop_user_id)
            .order_by(WorkshopContact.sort_order, WorkshopContact.id)
        )
    )


def list_project_selections(
    db: Session,
    workshop_user_id: UUID,
) -> list[tuple[WorkshopProjectSelection, Project]]:
    return list(
        db.execute(
            select(WorkshopProjectSelection, Project)
            .join(Project, Project.id == WorkshopProjectSelection.project_id)
            .where(WorkshopProjectSelection.workshop_user_id == workshop_user_id)
            .order_by(WorkshopProjectSelection.sort_order, WorkshopProjectSelection.id)
        ).tuples()
    )


def list_publication_social_accounts(
    db: Session,
    publication_id: UUID,
) -> list[WorkshopPublicationSocialAccount]:
    return list(
        db.scalars(
            select(WorkshopPublicationSocialAccount)
            .where(WorkshopPublicationSocialAccount.publication_id == publication_id)
            .order_by(
                WorkshopPublicationSocialAccount.sort_order,
                WorkshopPublicationSocialAccount.id,
            )
        )
    )


def list_publication_contacts(
    db: Session,
    publication_id: UUID,
) -> list[WorkshopPublicationContact]:
    return list(
        db.scalars(
            select(WorkshopPublicationContact)
            .where(WorkshopPublicationContact.publication_id == publication_id)
            .order_by(
                WorkshopPublicationContact.sort_order,
                WorkshopPublicationContact.id,
            )
        )
    )


def list_publication_project_cards(
    db: Session,
    publication_id: UUID,
) -> list[WorkshopPublicationProjectCard]:
    return list(
        db.scalars(
            select(WorkshopPublicationProjectCard)
            .where(WorkshopPublicationProjectCard.publication_id == publication_id)
            .order_by(
                WorkshopPublicationProjectCard.sort_order,
                WorkshopPublicationProjectCard.id,
            )
        )
    )


def get_brand_authorization(
    db: Session,
    creator_user_id: UUID,
    brand_id: UUID,
) -> WorkshopBrandAuthorization | None:
    return db.scalar(
        select(WorkshopBrandAuthorization).where(
            WorkshopBrandAuthorization.creator_user_id == creator_user_id,
            WorkshopBrandAuthorization.brand_id == brand_id,
        )
    )


def add_brand_authorization(
    db: Session,
    authorization: WorkshopBrandAuthorization,
) -> None:
    db.add(authorization)


def list_brand_authorizations(
    db: Session,
    creator_user_id: UUID,
) -> list[WorkshopBrandAuthorization]:
    return list(
        db.scalars(
            select(WorkshopBrandAuthorization)
            .where(
                WorkshopBrandAuthorization.creator_user_id == creator_user_id,
            )
            .order_by(
                WorkshopBrandAuthorization.active.desc(),
                WorkshopBrandAuthorization.granted_at.desc(),
                WorkshopBrandAuthorization.id.desc(),
            )
        )
    )


def list_discovery_publications(
    db: Session,
    brand_id: UUID,
    *,
    query: str | None,
    content_focus: str | None,
    creator_identity: str | None,
    project_type: str | None,
    followed: bool | None,
    sort_by: str,
    sort_order: str,
    limit: int,
    offset: int,
) -> tuple[list[WorkshopPublication], int]:
    authorization_exists = exists(
        select(1).where(
            WorkshopBrandAuthorization.creator_user_id == WorkshopPublication.workshop_user_id,
            WorkshopBrandAuthorization.brand_id == brand_id,
            WorkshopBrandAuthorization.active.is_(True),
        )
    )

    def visible(field_name: str):
        visibility = func.json_extract(
            WorkshopPublication.snapshot_json,
            f"$.{field_name}_visibility",
        )
        return or_(
            visibility.in_(("workshop_public", "brands_only")),
            and_(
                authorization_exists,
                visibility == "authorized_brands",
            ),
        )

    filters = [
        CreatorWorkshop.status == "published",
        CreatorWorkshop.published_revision_id == WorkshopPublication.id,
    ]
    if query:
        query_fields = (
            "nickname",
            "title",
            "bio",
            "creator_identity",
            "content_focus",
            "collaboration_preferences",
        )
        filters.append(
            or_(
                *(
                    and_(
                        visible(field),
                        cast(
                            func.json_extract(
                                WorkshopPublication.snapshot_json,
                                f"$.{field}",
                            ),
                            String,
                        ).contains(query, autoescape=True),
                    )
                    for field in query_fields
                )
            )
        )
    if content_focus:
        filters.append(
            and_(
                visible("content_focus"),
                cast(
                    func.json_extract(
                        WorkshopPublication.snapshot_json,
                        "$.content_focus",
                    ),
                    String,
                ).contains(f'"{content_focus}"', autoescape=True),
            )
        )
    if creator_identity:
        filters.append(
            and_(
                visible("creator_identity"),
                func.json_extract(
                    WorkshopPublication.snapshot_json,
                    "$.creator_identity",
                )
                == creator_identity,
            )
        )
    if project_type:
        filters.append(
            exists(
                select(1).where(
                    WorkshopPublicationProjectCard.publication_id == WorkshopPublication.id,
                    WorkshopPublicationProjectCard.type == project_type,
                    or_(
                        WorkshopPublicationProjectCard.visibility.in_(
                            ("workshop_public", "brands_only")
                        ),
                        and_(
                            authorization_exists,
                            WorkshopPublicationProjectCard.visibility == "authorized_brands",
                        ),
                    ),
                )
            )
        )
    active_follow_exists = exists(
        select(1).where(
            BrandFollow.brand_id == brand_id,
            BrandFollow.creator_user_id == WorkshopPublication.workshop_user_id,
            BrandFollow.status == "active",
        )
    )
    if followed is True:
        filters.append(active_follow_exists)
    elif followed is False:
        filters.append(~active_follow_exists)

    base = (
        select(WorkshopPublication)
        .join(
            CreatorWorkshop,
            CreatorWorkshop.user_id == WorkshopPublication.workshop_user_id,
        )
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    sort_column = (
        WorkshopPublication.updated_at
        if sort_by == "updated_at"
        else WorkshopPublication.published_at
    )
    order = (
        (sort_column.asc(), WorkshopPublication.id.asc())
        if sort_order == "asc"
        else (sort_column.desc(), WorkshopPublication.id.desc())
    )
    publications = list(db.scalars(base.order_by(*order).limit(limit).offset(offset)))
    return publications, int(total or 0)
