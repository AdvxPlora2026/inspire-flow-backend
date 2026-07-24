import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    IdempotencyKeyConflictError,
    IdempotencyKeyRequiredError,
    IdempotencyOutcomeUnknownError,
    IdempotencyReplay,
    IdempotencyRequestInProgressError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.idempotency import IdempotencyRecord
from inspire_flow_backend.data.repositories.idempotency import (
    add_idempotency_record,
    delete_expired_idempotency_records,
    get_agent_turn_run_by_idempotency_record,
    get_idempotency_record,
    get_idempotency_record_by_id,
    release_conversation_for_agent_turn,
)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
IDEMPOTENCY_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/users",
        "/api/v1/sessions",
        "/api/v1/sessions/current",
    }
)


def requires_idempotency(request: Request) -> bool:
    return (
        request.method.upper() in WRITE_METHODS and request.url.path not in IDEMPOTENCY_EXEMPT_PATHS
    )


async def prepare_idempotency(
    request: Request,
    *,
    db: Session,
    user_id: UUID,
    key: str | None,
    cipher: ContextCipher,
    brand_id: UUID | None = None,
    processing_timeout_seconds: int,
) -> None:
    if not requires_idempotency(request):
        return
    if key is None or not key.strip():
        raise IdempotencyKeyRequiredError
    normalized_key = key.strip()
    if not 8 <= len(normalized_key) <= 128 or not normalized_key.isascii():
        raise IdempotencyKeyRequiredError

    now = utc_now()
    delete_expired_idempotency_records(db, before=now)
    body = await _fingerprint_body(request)
    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    request_fingerprint = hashlib.sha256(
        b"\x1f".join(
            (
                request.method.upper().encode(),
                request.url.path.encode(),
                request.url.query.encode(),
                body,
            )
        )
    ).hexdigest()
    key_digest = hashlib.sha256(normalized_key.encode()).hexdigest()
    record = get_idempotency_record(
        db,
        user_id=user_id,
        brand_id=brand_id,
        method=request.method.upper(),
        route_template=route_template,
        key_digest=key_digest,
    )
    if record is not None:
        _replay_or_raise(
            db,
            record,
            request_fingerprint,
            cipher,
            now=now,
            processing_timeout_seconds=processing_timeout_seconds,
        )

    record = IdempotencyRecord(
        id=uuid4(),
        user_id=user_id,
        brand_id=brand_id,
        method=request.method.upper(),
        route_template=route_template,
        key_digest=key_digest,
        request_fingerprint=request_fingerprint,
        status="processing",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    add_idempotency_record(db, record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = get_idempotency_record(
            db,
            user_id=user_id,
            brand_id=brand_id,
            method=request.method.upper(),
            route_template=route_template,
            key_digest=key_digest,
        )
        if concurrent is None:
            raise
        _replay_or_raise(
            db,
            concurrent,
            request_fingerprint,
            cipher,
            now=now,
            processing_timeout_seconds=processing_timeout_seconds,
        )
    request.state.idempotency_record_id = record.id
    request.state.idempotency_db = db
    request.state.idempotency_cipher = cipher


async def _fingerprint_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "")
    if not content_type.casefold().startswith("multipart/form-data"):
        return await request.body()

    form = await request.form()
    parts: list[dict[str, object]] = []
    for field_name, value in form.multi_items():
        if isinstance(value, UploadFile):
            await value.seek(0)
            digest = hashlib.sha256()
            size = 0
            while chunk := await value.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            await value.seek(0)
            parts.append(
                {
                    "field": field_name,
                    "filename": value.filename,
                    "content_type": value.content_type,
                    "size": size,
                    "sha256": digest.hexdigest(),
                }
            )
        else:
            parts.append({"field": field_name, "value": str(value)})
    parts.sort(key=lambda part: json.dumps(part, sort_keys=True))
    return json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _replay_or_raise(
    db: Session,
    record: IdempotencyRecord,
    request_fingerprint: str,
    cipher: ContextCipher,
    *,
    now: datetime,
    processing_timeout_seconds: int,
) -> None:
    if record.request_fingerprint != request_fingerprint:
        raise IdempotencyKeyConflictError
    if record.status == "processing":
        if record.created_at <= now - timedelta(seconds=processing_timeout_seconds):
            run = get_agent_turn_run_by_idempotency_record(db, record.id)
            if run is not None and run.status == "processing":
                run.status = "failed"
                run.error_code = "idempotency_outcome_unknown"
                run.completed_at = now
                release_conversation_for_agent_turn(db, run.id)
            record.status = "failed"
            record.completed_at = now
            record.expires_at = now + timedelta(hours=24)
            db.commit()
            raise IdempotencyOutcomeUnknownError
        raise IdempotencyRequestInProgressError
    if record.response_ciphertext is None or record.response_status is None:
        raise IdempotencyOutcomeUnknownError
    cached = cipher.decrypt_json(record.response_ciphertext)
    if not isinstance(cached, dict) or "body" not in cached:
        raise IdempotencyRequestInProgressError
    headers = json.loads(record.response_headers or "{}")
    raise IdempotencyReplay(
        status_code=record.response_status,
        body=cached["body"],
        headers=headers if isinstance(headers, dict) else {},
    )


def complete_idempotency(
    request: Request,
    *,
    status_code: int,
    body: object,
    headers: dict[str, str],
) -> None:
    record_id = getattr(request.state, "idempotency_record_id", None)
    db = getattr(request.state, "idempotency_db", None)
    cipher = getattr(request.state, "idempotency_cipher", None)
    if record_id is None or not isinstance(db, Session) or not isinstance(cipher, ContextCipher):
        return
    complete_idempotency_record(
        db,
        record_id=record_id,
        cipher=cipher,
        status_code=status_code,
        body=body,
        headers=headers,
    )


def complete_idempotency_record(
    db: Session,
    *,
    record_id: UUID,
    cipher: ContextCipher,
    status_code: int,
    body: object,
    headers: dict[str, str],
) -> None:
    record = get_idempotency_record_by_id(db, record_id)
    if record is None:
        return
    now = utc_now()
    record.status = "completed" if status_code < 500 else "failed"
    record.response_status = status_code
    record.response_headers = json.dumps(headers, separators=(",", ":"), sort_keys=True)
    record.response_ciphertext = cipher.encrypt_json({"body": body})
    record.completed_at = now
    record.expires_at = now + timedelta(hours=24)
    db.commit()
