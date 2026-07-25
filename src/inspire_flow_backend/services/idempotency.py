import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
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
DEFAULT_RETENTION = timedelta(hours=24)


def requires_idempotency(request: Request) -> bool:
    return request.method.upper() in WRITE_METHODS


async def prepare_idempotency(
    request: Request,
    *,
    db: Session,
    user_id: UUID,
    key: str | None,
    cipher: ContextCipher,
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
    normalized_path = _normalized_path(request)
    request_fingerprint = hashlib.sha256(
        b"\x1f".join(
            (
                request.method.upper().encode(),
                normalized_path.encode(),
                _normalized_query(request),
                body,
            )
        )
    ).hexdigest()
    key_digest = hashlib.sha256(normalized_key.encode()).hexdigest()
    record = get_idempotency_record(
        db,
        user_id=user_id,
        method=request.method.upper(),
        route_template=normalized_path,
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
        brand_id=None,
        method=request.method.upper(),
        route_template=normalized_path,
        key_digest=key_digest,
        request_fingerprint=request_fingerprint,
        status="processing",
        created_at=now,
        expires_at=now + DEFAULT_RETENTION,
    )
    add_idempotency_record(db, record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = get_idempotency_record(
            db,
            user_id=user_id,
            method=request.method.upper(),
            route_template=normalized_path,
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
    normalized_content_type = content_type.partition(";")[0].strip().casefold()
    if normalized_content_type != "multipart/form-data":
        body = await request.body()
        if normalized_content_type == "application/json" or normalized_content_type.endswith(
            "+json"
        ):
            try:
                parsed = json.loads(body)
                return json.dumps(
                    parsed,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                return body
        return body

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


def _normalized_path(request: Request) -> str:
    path = request.scope.get("path")
    if not isinstance(path, str) or not path:
        path = request.url.path
    if path != "/":
        path = path.rstrip("/")
    return path or "/"


def _normalized_query(request: Request) -> bytes:
    items = sorted(request.query_params.multi_items())
    return json.dumps(
        items,
        ensure_ascii=False,
        separators=(",", ":"),
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
        raise IdempotencyKeyReusedError
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
            record.expires_at = now + DEFAULT_RETENTION
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
        retain_until=getattr(request.state, "idempotency_retain_until", None),
    )


def complete_idempotency_record(
    db: Session,
    *,
    record_id: UUID,
    cipher: ContextCipher,
    status_code: int,
    body: object,
    headers: dict[str, str],
    retain_until: datetime | None = None,
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
    record.expires_at = max(
        now + DEFAULT_RETENTION,
        _as_utc(retain_until) if retain_until is not None else now,
    )
    db.commit()


def retain_idempotency_until(request: Request, retain_until: datetime) -> None:
    normalized = _as_utc(retain_until)
    current = getattr(request.state, "idempotency_retain_until", None)
    if current is None or normalized > _as_utc(current):
        request.state.idempotency_retain_until = normalized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retention datetime must be timezone-aware")
    return value.astimezone(UTC)
