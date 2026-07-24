import json
import re
from uuid import UUID

from sqlalchemy.orm import Session

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    BrandAuthorizationNotFoundError,
    BrandNotFoundError,
    InvalidWorkshopContactError,
    ProjectNotFoundError,
    WorkshopItemNotFoundError,
    WorkshopNotFoundError,
    WorkshopNotPublishedError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.user import User
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
from inspire_flow_backend.data.repositories import brands as brand_repository
from inspire_flow_backend.data.repositories import projects as project_repository
from inspire_flow_backend.data.repositories import workshops as workshop_repository
from inspire_flow_backend.schemas.engagement import CreatorDiscoveryPage
from inspire_flow_backend.schemas.workshops import (
    WorkshopBrandAuthorizationPublic,
    WorkshopContactCreate,
    WorkshopContactPublic,
    WorkshopContactUpdate,
    WorkshopDraftPublic,
    WorkshopPreviewAudience,
    WorkshopProjectCardPublic,
    WorkshopProjectSelectionUpdate,
    WorkshopPublic,
    WorkshopSocialAccountCreate,
    WorkshopSocialAccountPublic,
    WorkshopSocialAccountUpdate,
    WorkshopUpdate,
)

WORKSHOP_FIELDS = (
    "nickname",
    "avatar_url",
    "title",
    "bio",
    "creator_identity",
    "content_focus",
    "collaboration_preferences",
)


def _new_workshop(user: User) -> CreatorWorkshop:
    now = utc_now()
    return CreatorWorkshop(
        user_id=user.id,
        status="draft",
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        title=None,
        bio=None,
        creator_identity=None,
        content_focus="[]",
        collaboration_preferences=None,
        nickname_visibility="workshop_public",
        avatar_visibility="workshop_public",
        title_visibility="workshop_public",
        bio_visibility="workshop_public",
        creator_identity_visibility="workshop_public",
        content_focus_visibility="workshop_public",
        collaboration_preferences_visibility="brands_only",
        created_at=now,
        updated_at=now,
    )


def _ensure_workshop(
    db: Session,
    user: User,
) -> CreatorWorkshop:
    workshop = workshop_repository.get_workshop(db, user.id)
    if workshop is not None:
        return workshop
    workshop = _new_workshop(user)
    workshop_repository.add_workshop(db, workshop)
    return workshop


def _decode_content_focus(value: str) -> list[str]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        return []
    return decoded


def _social_public(account: object, *, include_visibility: bool) -> WorkshopSocialAccountPublic:
    return WorkshopSocialAccountPublic(
        id=account.id,
        platform=account.platform,
        handle=account.handle,
        profile_url=account.profile_url,
        visibility=account.visibility if include_visibility else None,
        sort_order=account.sort_order,
    )


def _contact_value(contact: object, cipher: ContextCipher) -> str:
    plaintext = cipher.decrypt_text(contact.value_ciphertext)
    prefix = "workshop-contact-v1\x00"
    if not plaintext.startswith(prefix):
        raise ValueError("Invalid workshop contact ciphertext")
    return plaintext.removeprefix(prefix)


def _contact_action_uri(contact_type: str, value: str) -> str | None:
    if contact_type == "email":
        return f"mailto:{value}"
    if contact_type == "phone":
        return f"tel:{value}"
    if contact_type == "telegram":
        handle = value.removeprefix("@")
        return f"https://t.me/{handle}"
    return None


def _contact_public(
    contact: object,
    cipher: ContextCipher,
    *,
    include_visibility: bool,
) -> WorkshopContactPublic:
    value = _contact_value(contact, cipher)
    return WorkshopContactPublic(
        id=contact.id,
        type=contact.type,
        label=contact.label,
        value=value,
        action_uri=_contact_action_uri(contact.type, value),
        visibility=contact.visibility if include_visibility else None,
        sort_order=contact.sort_order,
    )


def _draft_project_public(selection: object, project: object) -> WorkshopProjectCardPublic:
    return WorkshopProjectCardPublic(
        project_id=project.id,
        title=project.title,
        type=project.type,
        audience=project.audience,
        summary=project.summary,
        icon_url=project.icon_url,
        visibility=selection.visibility,
        sort_order=selection.sort_order,
    )


def _draft_public(
    db: Session,
    workshop: CreatorWorkshop,
    cipher: ContextCipher,
) -> WorkshopDraftPublic:
    return WorkshopDraftPublic(
        user_id=workshop.user_id,
        status=workshop.status,
        nickname=workshop.nickname,
        avatar_url=workshop.avatar_url,
        title=workshop.title,
        bio=workshop.bio,
        creator_identity=workshop.creator_identity,
        content_focus=_decode_content_focus(workshop.content_focus),
        collaboration_preferences=workshop.collaboration_preferences,
        nickname_visibility=workshop.nickname_visibility,
        avatar_visibility=workshop.avatar_visibility,
        title_visibility=workshop.title_visibility,
        bio_visibility=workshop.bio_visibility,
        creator_identity_visibility=workshop.creator_identity_visibility,
        content_focus_visibility=workshop.content_focus_visibility,
        collaboration_preferences_visibility=workshop.collaboration_preferences_visibility,
        social_accounts=[
            _social_public(item, include_visibility=True)
            for item in workshop_repository.list_social_accounts(db, workshop.user_id)
        ],
        contacts=[
            _contact_public(item, cipher, include_visibility=True)
            for item in workshop_repository.list_contacts(db, workshop.user_id)
        ],
        projects=[
            _draft_project_public(selection, project)
            for selection, project in workshop_repository.list_project_selections(
                db,
                workshop.user_id,
            )
        ],
        published_at=workshop.published_at,
        created_at=workshop.created_at,
        updated_at=workshop.updated_at,
    )


def get_draft(
    db: Session,
    user: User,
    cipher: ContextCipher,
) -> WorkshopDraftPublic:
    workshop = workshop_repository.get_workshop(db, user.id)
    if workshop is None:
        workshop = _new_workshop(user)
    return _draft_public(db, workshop, cipher)


def update_draft(
    db: Session,
    user: User,
    payload: WorkshopUpdate,
    cipher: ContextCipher,
) -> WorkshopDraftPublic:
    workshop = _ensure_workshop(db, user)
    changed = False
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "avatar_url" and value is not None:
            value = str(value)
        elif field_name == "content_focus":
            value = json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))
        elif field_name.endswith("_visibility") and value is not None:
            value = value.value
        if getattr(workshop, field_name) != value:
            setattr(workshop, field_name, value)
            changed = True
    if changed:
        workshop.updated_at = utc_now()
    db.commit()
    db.refresh(workshop)
    return _draft_public(db, workshop, cipher)


def create_social_account(
    db: Session,
    user: User,
    payload: WorkshopSocialAccountCreate,
) -> WorkshopSocialAccountPublic:
    _ensure_workshop(db, user)
    now = utc_now()
    account = WorkshopSocialAccount(
        workshop_user_id=user.id,
        platform=payload.platform.value,
        handle=payload.handle.strip() if payload.handle else None,
        profile_url=str(payload.profile_url),
        visibility=payload.visibility.value,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    workshop_repository.add_social_account(db, account)
    db.commit()
    db.refresh(account)
    return _social_public(account, include_visibility=True)


def update_social_account(
    db: Session,
    user_id: UUID,
    account_id: UUID,
    payload: WorkshopSocialAccountUpdate,
) -> WorkshopSocialAccountPublic:
    account = workshop_repository.get_social_account(db, user_id, account_id)
    if account is None:
        raise WorkshopItemNotFoundError
    changed = False
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "profile_url" and value is not None:
            value = str(value)
        elif field_name in {"platform", "visibility"} and value is not None:
            value = value.value
        elif field_name == "handle" and value is not None:
            value = value.strip() or None
        if getattr(account, field_name) != value:
            setattr(account, field_name, value)
            changed = True
    if changed:
        account.updated_at = utc_now()
        db.commit()
        db.refresh(account)
    return _social_public(account, include_visibility=True)


def delete_social_account(
    db: Session,
    user_id: UUID,
    account_id: UUID,
) -> None:
    account = workshop_repository.get_social_account(db, user_id, account_id)
    if account is None:
        raise WorkshopItemNotFoundError
    workshop_repository.delete_social_account(db, account)
    db.commit()


def _normalize_contact_value(contact_type: str, value: str) -> str:
    normalized = value.strip()
    if contact_type == "email":
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized) is None:
            raise InvalidWorkshopContactError
        local, domain = normalized.rsplit("@", 1)
        return f"{local}@{domain.casefold()}"
    if contact_type == "phone":
        normalized = re.sub(r"[\s().-]", "", normalized)
        if re.fullmatch(r"\+?[0-9]{7,20}", normalized) is None:
            raise InvalidWorkshopContactError
        return normalized
    if contact_type == "qq" and re.fullmatch(r"[1-9][0-9]{4,14}", normalized) is None:
        raise InvalidWorkshopContactError
    if contact_type == "telegram":
        normalized = normalized.removeprefix("https://t.me/").removeprefix("@")
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", normalized) is None:
            raise InvalidWorkshopContactError
        return normalized
    if not normalized:
        raise InvalidWorkshopContactError
    return normalized


def _encrypt_contact_value(value: str, cipher: ContextCipher) -> str:
    return cipher.encrypt_text(f"workshop-contact-v1\x00{value}")


def create_contact(
    db: Session,
    user: User,
    payload: WorkshopContactCreate,
    cipher: ContextCipher,
) -> WorkshopContactPublic:
    _ensure_workshop(db, user)
    normalized_value = _normalize_contact_value(payload.type.value, payload.value)
    now = utc_now()
    contact = WorkshopContact(
        workshop_user_id=user.id,
        type=payload.type.value,
        label=payload.label.strip() if payload.label else None,
        value_ciphertext=_encrypt_contact_value(normalized_value, cipher),
        visibility=payload.visibility.value,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    workshop_repository.add_contact(db, contact)
    db.commit()
    db.refresh(contact)
    return _contact_public(contact, cipher, include_visibility=True)


def update_contact(
    db: Session,
    user_id: UUID,
    contact_id: UUID,
    payload: WorkshopContactUpdate,
    cipher: ContextCipher,
) -> WorkshopContactPublic:
    contact = workshop_repository.get_contact(db, user_id, contact_id)
    if contact is None:
        raise WorkshopItemNotFoundError
    next_type = payload.type.value if payload.type is not None else contact.type
    changed = False
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "type" and value is not None:
            value = value.value
        elif field_name == "visibility" and value is not None:
            value = value.value
        elif field_name == "value" and value is not None:
            normalized = _normalize_contact_value(next_type, value)
            current = _contact_value(contact, cipher)
            value = (
                contact.value_ciphertext
                if normalized == current
                else _encrypt_contact_value(normalized, cipher)
            )
            field_name = "value_ciphertext"
        elif field_name == "label" and value is not None:
            value = value.strip() or None
        if getattr(contact, field_name) != value:
            setattr(contact, field_name, value)
            changed = True
    if "type" in payload.model_fields_set and "value" not in payload.model_fields_set:
        current = _contact_value(contact, cipher)
        _normalize_contact_value(contact.type, current)
    if changed:
        contact.updated_at = utc_now()
        db.commit()
        db.refresh(contact)
    return _contact_public(contact, cipher, include_visibility=True)


def delete_contact(
    db: Session,
    user_id: UUID,
    contact_id: UUID,
) -> None:
    contact = workshop_repository.get_contact(db, user_id, contact_id)
    if contact is None:
        raise WorkshopItemNotFoundError
    workshop_repository.delete_contact(db, contact)
    db.commit()


def set_project_selection(
    db: Session,
    user: User,
    project_id: UUID,
    payload: WorkshopProjectSelectionUpdate,
) -> WorkshopProjectCardPublic:
    project = project_repository.get_project(db, user.id, project_id)
    if project is None:
        raise ProjectNotFoundError
    _ensure_workshop(db, user)
    selection = workshop_repository.get_project_selection(db, user.id, project_id)
    now = utc_now()
    if selection is None:
        selection = WorkshopProjectSelection(
            workshop_user_id=user.id,
            project_id=project_id,
            visibility=payload.visibility.value,
            sort_order=payload.sort_order,
            created_at=now,
            updated_at=now,
        )
        workshop_repository.add_project_selection(db, selection)
    else:
        changed = False
        if selection.visibility != payload.visibility.value:
            selection.visibility = payload.visibility.value
            changed = True
        if selection.sort_order != payload.sort_order:
            selection.sort_order = payload.sort_order
            changed = True
        if changed:
            selection.updated_at = now
    db.commit()
    db.refresh(selection)
    return _draft_project_public(selection, project)


def delete_project_selection(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> None:
    selection = workshop_repository.get_project_selection(db, user_id, project_id)
    if selection is None:
        raise WorkshopItemNotFoundError
    workshop_repository.delete_project_selection(db, selection)
    db.commit()


def _snapshot(workshop: CreatorWorkshop) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for field_name in WORKSHOP_FIELDS:
        value = getattr(workshop, field_name)
        if field_name == "content_focus":
            value = _decode_content_focus(value)
        snapshot[field_name] = value
        visibility_name = (
            "avatar_visibility" if field_name == "avatar_url" else f"{field_name}_visibility"
        )
        snapshot[visibility_name] = getattr(workshop, visibility_name)
    return snapshot


def publish_workshop(
    db: Session,
    user: User,
    cipher: ContextCipher,
) -> WorkshopPublic:
    workshop = _ensure_workshop(db, user)
    now = utc_now()
    publication = WorkshopPublication(
        workshop_user_id=user.id,
        version=workshop_repository.next_publication_version(db, user.id),
        snapshot_json=json.dumps(
            _snapshot(workshop),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        published_at=now,
        updated_at=workshop.updated_at,
    )
    workshop_repository.add_publication(db, publication)
    db.flush()
    publication_items: list[
        WorkshopPublicationSocialAccount
        | WorkshopPublicationContact
        | WorkshopPublicationProjectCard
    ] = [
        WorkshopPublicationSocialAccount(
            publication_id=publication.id,
            platform=item.platform,
            handle=item.handle,
            profile_url=item.profile_url,
            visibility=item.visibility,
            sort_order=item.sort_order,
        )
        for item in workshop_repository.list_social_accounts(db, user.id)
    ]
    publication_items.extend(
        WorkshopPublicationContact(
            publication_id=publication.id,
            type=item.type,
            label=item.label,
            value_ciphertext=item.value_ciphertext,
            visibility=item.visibility,
            sort_order=item.sort_order,
        )
        for item in workshop_repository.list_contacts(db, user.id)
    )
    publication_items.extend(
        WorkshopPublicationProjectCard(
            publication_id=publication.id,
            source_project_id=project.id,
            title=project.title,
            type=project.type,
            audience=project.audience,
            summary=project.summary,
            icon_url=project.icon_url,
            visibility=selection.visibility,
            sort_order=selection.sort_order,
        )
        for selection, project in workshop_repository.list_project_selections(
            db,
            user.id,
        )
    )
    workshop_repository.add_publication_items(db, publication_items)
    workshop.status = "published"
    workshop.published_revision_id = publication.id
    workshop.published_at = now
    workshop.updated_at = now
    db.commit()
    db.refresh(workshop)
    return _project_publication(
        db,
        publication,
        audience="owner",
        cipher=cipher,
    )


def withdraw_workshop(
    db: Session,
    user_id: UUID,
    cipher: ContextCipher,
) -> WorkshopDraftPublic:
    workshop = workshop_repository.get_workshop(db, user_id)
    if workshop is None or workshop.status != "published" or workshop.published_revision_id is None:
        raise WorkshopNotPublishedError
    workshop.status = "withdrawn"
    workshop.updated_at = utc_now()
    db.commit()
    db.refresh(workshop)
    return _draft_public(db, workshop, cipher)


def _visibility_allows(visibility: str, audience: str) -> bool:
    if audience == "owner":
        return True
    if visibility == "workshop_public":
        return True
    if audience in {"brand", "authorized_brand"} and visibility == "brands_only":
        return True
    return audience == "authorized_brand" and visibility == "authorized_brands"


def _project_snapshot_fields(
    snapshot: dict[str, object],
    audience: str,
) -> dict[str, object]:
    projected: dict[str, object] = {}
    for field_name in WORKSHOP_FIELDS:
        visibility_name = (
            "avatar_visibility" if field_name == "avatar_url" else f"{field_name}_visibility"
        )
        visibility = snapshot.get(visibility_name)
        projected[field_name] = (
            snapshot.get(field_name)
            if isinstance(visibility, str) and _visibility_allows(visibility, audience)
            else None
        )
    return projected


def _project_publication(
    db: Session,
    publication: WorkshopPublication,
    *,
    audience: str,
    cipher: ContextCipher,
) -> WorkshopPublic:
    decoded = json.loads(publication.snapshot_json)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid workshop publication snapshot")
    fields = _project_snapshot_fields(decoded, audience)
    social_accounts = [
        _social_public(item, include_visibility=False)
        for item in workshop_repository.list_publication_social_accounts(
            db,
            publication.id,
        )
        if _visibility_allows(item.visibility, audience)
    ]
    contacts = [
        _contact_public(item, cipher, include_visibility=False)
        for item in workshop_repository.list_publication_contacts(db, publication.id)
        if _visibility_allows(item.visibility, audience)
    ]
    projects = [
        WorkshopProjectCardPublic(
            project_id=item.source_project_id,
            title=item.title,
            type=item.type,
            audience=item.audience,
            summary=item.summary,
            icon_url=item.icon_url,
            visibility=None,
            sort_order=item.sort_order,
        )
        for item in workshop_repository.list_publication_project_cards(
            db,
            publication.id,
        )
        if _visibility_allows(item.visibility, audience)
    ]
    return WorkshopPublic(
        creator_id=publication.workshop_user_id,
        **fields,
        social_accounts=social_accounts,
        contacts=contacts,
        projects=projects,
        published_at=publication.published_at,
    )


def preview_workshop(
    db: Session,
    user: User,
    audience: WorkshopPreviewAudience,
    cipher: ContextCipher,
) -> WorkshopPublic:
    workshop = workshop_repository.get_workshop(db, user.id)
    if workshop is None:
        workshop = _new_workshop(user)
    projected = _project_snapshot_fields(_snapshot(workshop), audience.value)
    social_accounts = [
        _social_public(item, include_visibility=False)
        for item in workshop_repository.list_social_accounts(db, user.id)
        if _visibility_allows(item.visibility, audience.value)
    ]
    contacts = [
        _contact_public(item, cipher, include_visibility=False)
        for item in workshop_repository.list_contacts(db, user.id)
        if _visibility_allows(item.visibility, audience.value)
    ]
    projects = [
        WorkshopProjectCardPublic(
            **_draft_project_public(selection, project).model_dump(exclude={"visibility"}),
            visibility=None,
        )
        for selection, project in workshop_repository.list_project_selections(
            db,
            user.id,
        )
        if _visibility_allows(selection.visibility, audience.value)
    ]
    return WorkshopPublic(
        creator_id=user.id,
        **projected,
        social_accounts=social_accounts,
        contacts=contacts,
        projects=projects,
        published_at=workshop.published_at,
    )


def read_public_workshop(
    db: Session,
    creator_id: UUID,
    *,
    viewer_user_id: UUID | None,
    brand_id: UUID | None,
    cipher: ContextCipher,
) -> WorkshopPublic:
    workshop = workshop_repository.get_workshop(db, creator_id)
    if workshop is None or workshop.status != "published" or workshop.published_revision_id is None:
        raise WorkshopNotPublishedError
    publication = workshop_repository.get_publication(
        db,
        workshop.published_revision_id,
    )
    if publication is None:
        raise WorkshopNotPublishedError

    audience = "owner" if viewer_user_id == creator_id else "public"
    if brand_id is not None and viewer_user_id != creator_id:
        if viewer_user_id is None:
            raise BrandNotFoundError
        membership = brand_repository.get_membership(db, brand_id, viewer_user_id)
        if membership is None:
            raise BrandNotFoundError
        authorization = workshop_repository.get_brand_authorization(
            db,
            creator_id,
            brand_id,
        )
        audience = (
            "authorized_brand" if authorization is not None and authorization.active else "brand"
        )
    return _project_publication(
        db,
        publication,
        audience=audience,
        cipher=cipher,
    )


def discover_workshops(
    db: Session,
    brand_id: UUID,
    member_user_id: UUID,
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
    cipher: ContextCipher,
) -> CreatorDiscoveryPage:
    membership = brand_repository.get_membership(db, brand_id, member_user_id)
    brand = brand_repository.get_brand(db, brand_id)
    if membership is None or brand is None:
        raise BrandNotFoundError
    publications, total = workshop_repository.list_discovery_publications(
        db,
        brand_id,
        query=query,
        content_focus=content_focus,
        creator_identity=creator_identity,
        project_type=project_type,
        followed=followed,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    items: list[WorkshopPublic] = []
    for publication in publications:
        authorization = workshop_repository.get_brand_authorization(
            db,
            publication.workshop_user_id,
            brand_id,
        )
        items.append(
            _project_publication(
                db,
                publication,
                audience=(
                    "authorized_brand"
                    if authorization is not None and authorization.active
                    else "brand"
                ),
                cipher=cipher,
            )
        )
    return CreatorDiscoveryPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


def grant_brand_authorization(
    db: Session,
    creator_user_id: UUID,
    brand_id: UUID,
) -> WorkshopBrandAuthorizationPublic:
    workshop = workshop_repository.get_workshop(db, creator_user_id)
    brand = brand_repository.get_brand(db, brand_id)
    if workshop is None:
        raise WorkshopNotFoundError
    if brand is None:
        raise BrandNotFoundError
    authorization = workshop_repository.get_brand_authorization(
        db,
        creator_user_id,
        brand_id,
    )
    now = utc_now()
    if authorization is None:
        authorization = WorkshopBrandAuthorization(
            creator_user_id=creator_user_id,
            brand_id=brand_id,
            active=True,
            granted_at=now,
        )
        workshop_repository.add_brand_authorization(db, authorization)
    elif not authorization.active:
        authorization.active = True
        authorization.granted_at = now
        authorization.revoked_at = None
    db.commit()
    db.refresh(authorization)
    return WorkshopBrandAuthorizationPublic(
        brand_id=brand.id,
        brand_name=brand.name,
        active=authorization.active,
        granted_at=authorization.granted_at,
        revoked_at=authorization.revoked_at,
    )


def revoke_brand_authorization(
    db: Session,
    creator_user_id: UUID,
    brand_id: UUID,
) -> None:
    authorization = workshop_repository.get_brand_authorization(
        db,
        creator_user_id,
        brand_id,
    )
    if authorization is None or not authorization.active:
        raise BrandAuthorizationNotFoundError
    authorization.active = False
    authorization.revoked_at = utc_now()
    db.commit()


def list_brand_authorizations(
    db: Session,
    creator_user_id: UUID,
) -> list[WorkshopBrandAuthorizationPublic]:
    results: list[WorkshopBrandAuthorizationPublic] = []
    for authorization in workshop_repository.list_brand_authorizations(
        db,
        creator_user_id,
    ):
        brand = brand_repository.get_brand(db, authorization.brand_id)
        if brand is None:
            continue
        results.append(
            WorkshopBrandAuthorizationPublic(
                brand_id=brand.id,
                brand_name=brand.name,
                active=authorization.active,
                granted_at=authorization.granted_at,
                revoked_at=authorization.revoked_at,
            )
        )
    return results
