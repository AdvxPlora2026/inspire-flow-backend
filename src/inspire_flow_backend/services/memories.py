from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.context_security import ContextCipher, redact_credentials
from inspire_flow_backend.core.errors import (
    CredentialMemoryForbiddenError,
    MemoryNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.repositories.memories import (
    add_memory,
    get_memory,
    get_memory_by_fingerprint,
    list_memories,
)
from inspire_flow_backend.data.repositories.memories import (
    delete_memory as delete_memory_record,
)
from inspire_flow_backend.schemas.memories import (
    MemoryCategory,
    MemoryOrigin,
    MemoryStatus,
    UserMemoryCreate,
    UserMemoryPage,
    UserMemoryPublic,
    UserMemoryUpdate,
)


def store_memory(
    db: Session,
    *,
    user_id: UUID,
    category: MemoryCategory | str,
    content: str,
    origin: MemoryOrigin | str,
    is_sensitive: bool,
    cipher: ContextCipher,
    status: MemoryStatus | str = MemoryStatus.active,
    is_pinned: bool = False,
    source_conversation_id: UUID | None = None,
    source_message_id: UUID | None = None,
) -> UserMemory:
    normalized_content = " ".join(content.split())
    redaction = redact_credentials(normalized_content)
    if not normalized_content:
        raise ValueError("Memory content cannot be blank")
    if len(normalized_content) > 2000:
        raise ValueError("Memory content cannot exceed 2000 characters")
    if redaction.was_redacted:
        raise CredentialMemoryForbiddenError

    category_value = MemoryCategory(category).value
    origin_value = MemoryOrigin(origin).value
    status_value = MemoryStatus(status).value
    fingerprint = cipher.fingerprint(user_id, category_value, normalized_content)
    existing = get_memory_by_fingerprint(db, user_id, fingerprint)
    if existing is not None:
        return existing

    now = utc_now()
    memory = UserMemory(
        user_id=user_id,
        category=category_value,
        content_ciphertext=cipher.encrypt_text(normalized_content),
        content_fingerprint=fingerprint,
        status=status_value,
        origin=origin_value,
        is_sensitive=is_sensitive,
        is_pinned=is_pinned,
        user_edited=False,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        created_at=now,
        updated_at=now,
    )
    add_memory(db, memory)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_memory_by_fingerprint(db, user_id, fingerprint)
        if existing is None:
            raise
        return existing
    db.refresh(memory)
    return memory


def create_manual_memory(
    db: Session,
    user_id: UUID,
    payload: UserMemoryCreate,
    cipher: ContextCipher,
) -> UserMemoryPublic:
    memory = store_memory(
        db,
        user_id=user_id,
        category=payload.category,
        content=payload.content,
        origin=MemoryOrigin.manual,
        is_sensitive=payload.is_sensitive,
        cipher=cipher,
        status=payload.status,
        is_pinned=payload.is_pinned,
    )
    return to_public_memory(memory, cipher)


def get_public_memory(
    db: Session,
    user_id: UUID,
    memory_id: UUID,
    cipher: ContextCipher,
) -> UserMemoryPublic:
    memory = get_memory(db, user_id, memory_id)
    if memory is None:
        raise MemoryNotFoundError
    return to_public_memory(memory, cipher)


def list_public_memories(
    db: Session,
    user_id: UUID,
    *,
    status: MemoryStatus | None,
    category: MemoryCategory | None,
    limit: int,
    offset: int,
    cipher: ContextCipher,
) -> UserMemoryPage:
    memories, total = list_memories(
        db,
        user_id,
        status=status.value if status is not None else None,
        category=category.value if category is not None else None,
        limit=limit,
        offset=offset,
    )
    return UserMemoryPage(
        items=[to_public_memory(memory, cipher) for memory in memories],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_memory(
    db: Session,
    user_id: UUID,
    memory_id: UUID,
    payload: UserMemoryUpdate,
    cipher: ContextCipher,
) -> UserMemoryPublic:
    memory = get_memory(db, user_id, memory_id)
    if memory is None:
        raise MemoryNotFoundError

    current_content = cipher.decrypt_text(memory.content_ciphertext)
    next_category = (
        payload.category.value
        if "category" in payload.model_fields_set and payload.category is not None
        else memory.category
    )
    next_content = (
        payload.content
        if "content" in payload.model_fields_set and payload.content is not None
        else current_content
    )
    redaction = redact_credentials(next_content)
    if redaction.was_redacted:
        raise CredentialMemoryForbiddenError

    changes: dict[str, object] = {}
    field_values = {
        "category": next_category,
        "content_ciphertext": (
            cipher.encrypt_text(next_content)
            if next_content != current_content
            else memory.content_ciphertext
        ),
        "content_fingerprint": cipher.fingerprint(
            user_id,
            next_category,
            next_content,
        ),
        "status": payload.status.value if payload.status is not None else memory.status,
        "is_sensitive": (
            payload.is_sensitive if payload.is_sensitive is not None else memory.is_sensitive
        ),
        "is_pinned": (payload.is_pinned if payload.is_pinned is not None else memory.is_pinned),
    }
    for field_name, value in field_values.items():
        if getattr(memory, field_name) != value:
            changes[field_name] = value

    if not changes:
        return to_public_memory(memory, cipher)

    for field_name, value in changes.items():
        setattr(memory, field_name, value)
    memory.user_edited = True
    memory.updated_at = utc_now()
    db.commit()
    db.refresh(memory)
    return to_public_memory(memory, cipher)


def delete_memory(
    db: Session,
    user_id: UUID,
    memory_id: UUID,
) -> None:
    memory = get_memory(db, user_id, memory_id)
    if memory is None:
        raise MemoryNotFoundError
    delete_memory_record(db, memory)
    db.commit()


def to_public_memory(
    memory: UserMemory,
    cipher: ContextCipher,
) -> UserMemoryPublic:
    return UserMemoryPublic(
        id=memory.id,
        user_id=memory.user_id,
        category=MemoryCategory(memory.category),
        content=cipher.decrypt_text(memory.content_ciphertext),
        status=MemoryStatus(memory.status),
        origin=MemoryOrigin(memory.origin),
        is_sensitive=memory.is_sensitive,
        is_pinned=memory.is_pinned,
        user_edited=memory.user_edited,
        source_conversation_id=memory.source_conversation_id,
        source_deleted_at=memory.source_deleted_at,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
